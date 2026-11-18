# ruff: noqa: E501
"""Thumbnails (Fase 9B): escolha dos frames, composição com FFmpeg e variações determinísticas (plano 6.7).

Sem Pillow e sem IA de imagem: o FFmpeg corta o frame da gravação, corrige a cor, aplica a moldura e desenha o texto e o
selo de dia com a identidade do brand kit. A parte pura (quebra de texto, posição, filtro, nome com hash, variações) roda
em `dev` sem FFmpeg; o executor chama o FFmpeg e só se confere com mídia real em `prod`.

Variação N = o N-ésimo melhor frame + o N-ésimo texto + a N-ésima posição do modelo (volta ao começo se faltar). Mesma
entrada, mesmos arquivos (o nome leva o hash do filtro, do frame de moldura e da qualidade do JPEG).
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np

from cronista.config import Settings
from cronista.finishing.brand import Visual
from cronista.finishing.render.atomic import render_to
from cronista.finishing.render.overlay import SYSTEM_FONTS, drawtext_escape, ffmpeg_color, find_font
from cronista.finishing.render.video import filter_path
from cronista.ingest.ffmpeg import run_ffmpeg
from cronista.pipeline.gpu import GpuGate, wait_until_free
from cronista.pipeline.stage import StageError
from cronista.thumbnails.frames import (
    GrayImage,
    ScoredFrame,
    measure_frame,
    moments_from_story_pack,
    pick_frames,
    plan_samples,
    score_frame,
)
from cronista.thumbnails.model import Position, ThumbnailModel, resolve_color

PROBE_W, PROBE_H = 480, 270
MAX_BYTES = 2_000_000
"""Limite de tamanho da thumbnail no YouTube (2 MB)."""
JPEG_QUALITIES = (3, 6, 10)
"""`-q:v` do FFmpeg, do melhor para o menor: o primeiro que couber em `MAX_BYTES` vale."""
CHAR_ASPECT = 0.6
"""Largura média de um caractere em fração da altura da fonte (estimativa para caber o texto na imagem)."""
LINE_SPACING = 1.05


class ThumbnailError(Exception):
    """Thumbnail não pôde ser gerada; a mensagem já diz o que fazer."""


# --- texto -----------------------------------------------------------------------------------------------


def prepare_text(text: str, uppercase: bool) -> str:
    clean = " ".join(text.split())
    return clean.upper() if uppercase else clean


def wrap_text(text: str, max_line_chars: int) -> list[str]:
    """Uma linha se couber; senão duas, na quebra que deixa as linhas mais parecidas (nunca três)."""
    words = text.split()
    if not words:
        return []
    if len(text) <= max_line_chars or len(words) == 1:
        return [text]
    best = min(
        range(1, len(words)),
        key=lambda i: (max(len(" ".join(words[:i])), len(" ".join(words[i:]))), i),
    )
    return [" ".join(words[:best]), " ".join(words[best:])]


def fit_font_size(lines: Sequence[str], size_px: int, width: int, margin_px: int) -> int:
    """Reduz a fonte se a linha mais longa não couber entre as margens (estimativa por largura média de caractere)."""
    longest = max((len(line) for line in lines), default=0)
    available = width - 2 * margin_px
    if longest == 0 or longest * size_px * CHAR_ASPECT <= available:
        return size_px
    return max(8, int(available / (longest * CHAR_ASPECT)))


def line_positions(
    position: Position, lines: int, font_px: int, width: int, height: int, margin_px: int
) -> list[tuple[str, str]]:
    """Expressões `x`, `y` do drawtext de cada linha do bloco de texto, ancorado na posição escolhida."""
    line_h = round(font_px * LINE_SPACING)
    block = line_h * lines
    if position.startswith("topo"):
        top = margin_px
    elif position.startswith("base"):
        top = height - margin_px - block
    else:
        top = (height - block) // 2
    if position.endswith("esquerda"):
        x = f"{margin_px}"
    elif position.endswith("direita"):
        x = f"w-text_w-{margin_px}"
    else:
        x = "(w-text_w)/2"
    return [(x, str(top + i * line_h)) for i in range(lines)]


# --- filtro ----------------------------------------------------------------------------------------------


def _num(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _drawtext(font: Path, text: str, size: int, x: str, y: str, color: str, extra: str = "") -> str:
    return (
        f"drawtext=fontfile='{filter_path(font)}':text='{drawtext_escape(text)}':fontsize={size}"
        f":fontcolor={ffmpeg_color(color)}:x={x}:y={y}{extra}"
    )


def pick_font(
    brand_dir: Path | None, visual: Visual, which: str, system: Sequence[str] = SYSTEM_FONTS
) -> Path | None:
    """`title` = primeira fonte do brand kit, `body` = a segunda (ou a primeira, se só houver uma); senão, a do sistema."""
    if brand_dir is not None:
        files = [brand_dir / f for f in visual.fonts.files if (brand_dir / f).is_file()]
        if files:
            return files[1] if which == "body" and len(files) > 1 else files[0]
    return find_font(None, visual, system)


def build_chain(
    model: ThumbnailModel,
    visual: Visual,
    font: Path,
    *,
    text: str | None,
    position: Position,
    day: int | None,
    frame_png: Path | None,
) -> str:
    """Grafo de filtros da entrada `[0:v]` (e `[1:v]` = moldura) até a saída `[v]`."""
    w, h = model.width, model.height
    pal = visual.palette
    grade = model.color
    parts = [
        f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1",
        f"eq=saturation={_num(grade.saturation)}:contrast={_num(grade.contrast)}:brightness={_num(grade.brightness)}",
    ]
    if grade.vignette:
        parts.append("vignette=PI/5")
    head = "[0:v]" + ",".join(parts)
    if frame_png is not None:
        head += f"[b];[1:v]scale={w}:{h}[f];[b][f]overlay=0:0"
    draws: list[str] = []
    if text:
        style = model.text
        margin = round(h * style.margin_pct)
        lines = wrap_text(prepare_text(text, style.uppercase), style.max_line_chars)
        size = fit_font_size(lines, round(h * style.size_pct), w, margin)
        stroke = round(h * style.stroke_pct)
        extra = (
            f":borderw={stroke}:bordercolor={ffmpeg_color(resolve_color(style.stroke_color, pal))}"
            if stroke
            else ""
        )
        for line, (x, y) in zip(lines, line_positions(position, len(lines), size, w, h, margin), strict=True):
            draws.append(_drawtext(font, line, size, x, y, resolve_color(style.color, pal), extra))
    badge = model.day_badge
    if badge.enabled and day is not None:
        pad = round(h * 0.02)
        margin = round(h * model.text.margin_pct)
        size = round(h * badge.size_pct)
        ((x, y),) = line_positions(badge.position, 1, size + 2 * pad, w, h, margin)
        box = f":box=1:boxcolor={ffmpeg_color(resolve_color(badge.fill, pal))}:boxborderw={pad}"
        draws.append(
            _drawtext(
                font,
                badge.template.replace("{n}", str(day)),
                size,
                x,
                y,
                resolve_color(badge.color, pal),
                box,
            )
        )
    chain = head + ("," + ",".join(draws) if draws else "")
    return f"{chain},format=yuvj420p[v]"


# --- variações -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Variation:
    n: int
    frame: ScoredFrame
    text: str | None
    position: Position


def plan_variations(
    frames: Sequence[ScoredFrame], texts: Sequence[str], model: ThumbnailModel, count: int = 3
) -> list[Variation]:
    """Variação N: o N-ésimo melhor frame, o N-ésimo texto e a N-ésima posição (cada lista volta ao começo)."""
    if not frames:
        return []
    out: list[Variation] = []
    for n in range(min(count, max(len(frames), len(texts)))):
        out.append(
            Variation(
                n + 1,
                frames[n % len(frames)],
                texts[n % len(texts)] if texts else None,
                model.text.positions[n % len(model.text.positions)],
            )
        )
    return out


def thumb_name(v: Variation, chain: str, frame_digest: str, quality: int) -> str:
    digest = hashlib.sha256("|".join([chain, frame_digest, str(quality)]).encode()).hexdigest()[:10]
    return f"thumb-{v.frame.file_id}-{round(v.frame.t_s * 1000)}-v{v.n}-{digest}.jpg"


def file_digest(path: Path | None) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path is not None else "-"


# --- FFmpeg ----------------------------------------------------------------------------------------------


def grab_gray(settings: Settings, master: Path, t_s: float) -> GrayImage | None:
    """Um frame da gravação em tons de cinza (480x270) para medir; `None` se o FFmpeg não entregou o frame."""
    cmd = [
        settings.ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{t_s:.3f}", "-i", str(master),
        "-frames:v", "1", "-vf", f"scale={PROBE_W}:{PROBE_H},format=gray", "-f", "rawvideo", "-",
    ]  # fmt: skip
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0 or len(proc.stdout) != PROBE_W * PROBE_H:
        return None
    return np.frombuffer(proc.stdout, dtype=np.uint8).reshape(PROBE_H, PROBE_W)


GrabFn = Callable[[Path, float], "GrayImage | None"]


def choose_frames(
    story_pack: Mapping[str, Any], masters: Mapping[int, Path], grab: GrabFn, count: int = 3
) -> tuple[list[ScoredFrame], list[str]]:
    """Amostra os picos do story-pack, mede cada frame e devolve os melhores (e avisos do que não deu para medir)."""
    warnings: list[str] = []
    scored: list[ScoredFrame] = []
    for sample in plan_samples(moments_from_story_pack(story_pack)):
        master = masters.get(sample.moment.file_id)
        if master is None:
            note = f"gravação {sample.moment.file_id} sem arquivo mestre; ignorada"
            if note not in warnings:
                warnings.append(note)
            continue
        gray = grab(master, sample.t_s)
        if gray is None:
            continue
        scored.append(score_frame(sample, measure_frame(gray)))
    return pick_frames(scored, count), warnings


def _compose(
    settings: Settings, master: Path, t_s: float, chain: str, frame_png: Path | None, q: int, out: Path
) -> None:
    args = ["-ss", f"{t_s:.3f}", "-i", str(master)]
    if frame_png is not None:
        args += ["-i", str(frame_png)]
    args += ["-filter_complex", chain, "-map", "[v]", "-frames:v", "1", "-q:v", str(q), str(out)]
    run_ffmpeg(settings, args)


@dataclass
class ThumbnailItem:
    variation: Variation
    path: Path


@dataclass
class ThumbnailsRender:
    items: list[ThumbnailItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def render_thumbnails(
    story_pack: Mapping[str, Any],
    masters: Mapping[int, Path],
    model: ThumbnailModel,
    visual: Visual,
    out_dir: Path,
    settings: Settings,
    *,
    texts: Sequence[str] = (),
    day: int | None = None,
    count: int = 3,
    brand_dir: Path | None = None,
    gate: GpuGate | None = None,
    grab: GrabFn | None = None,
) -> ThumbnailsRender:
    """Escolhe os frames e gera as variações em JPEG (≤ 2 MB). Reaproveita o que já existe (nome com hash)."""
    font = pick_font(brand_dir, visual, model.text.font)
    if font is None:
        raise ThumbnailError(
            "nenhuma fonte encontrada (declare `fonts.files` no brand kit); thumbnail recusada"
        )
    frame_png: Path | None = None
    if model.frame:
        frame_png = (brand_dir / model.frame) if brand_dir is not None else Path(model.frame)
        if not frame_png.is_file():
            raise ThumbnailError(f"moldura {model.frame!r} não existe; corrija `thumbnail.yaml`")
    result = ThumbnailsRender()
    grab_fn: GrabFn = grab or partial(grab_gray, settings)
    frames, notes = choose_frames(story_pack, masters, grab_fn, count)
    result.warnings.extend(notes)
    if not frames:
        result.warnings.append(
            "nenhum frame candidato (story-pack sem beats ou gravações sem arquivo mestre)"
        )
        return result
    if not texts:
        result.warnings.append("sem texto de thumbnail: só o frame (passe --texto ou rode /titular)")
    if model.day_badge.enabled and day is None:
        result.warnings.append(
            "selo de dia ligado, mas sem `--dia`: o número é decidido na edição; selo omitido"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = file_digest(frame_png)
    for v in plan_variations(frames, texts, model, count):
        chain = build_chain(
            model, visual, font, text=v.text, position=v.position, day=day, frame_png=frame_png
        )
        found = next(
            (p for q in JPEG_QUALITIES if (p := out_dir / thumb_name(v, chain, digest, q)).is_file()), None
        )
        if found is not None and found.stat().st_size > 0:
            result.items.append(ThumbnailItem(v, found))
            continue
        if gate is not None:  # a GPU é a mesma do OBS e do jogo
            wait_until_free(gate, settings.gpu_poll_seconds, etapa="thumbnail", arquivo=f"v{v.n}")
        master = masters[v.frame.file_id]
        target = out_dir / thumb_name(v, chain, digest, JPEG_QUALITIES[0])
        for q in JPEG_QUALITIES:
            target = out_dir / thumb_name(v, chain, digest, q)
            try:
                render_to(target, partial(_compose, settings, master, v.frame.t_s, chain, frame_png, q))
            except StageError as exc:
                raise ThumbnailError(str(exc)) from exc
            if target.stat().st_size <= MAX_BYTES:
                break
            if q != JPEG_QUALITIES[-1]:
                target.unlink()  # grande demais: só a versão menor fica (o reaproveitamento acha um arquivo só)
        else:
            result.warnings.append(f"variação {v.n}: {target.stat().st_size} bytes, acima de 2 MB do YouTube")
        result.items.append(ThumbnailItem(v, target))
    return result
