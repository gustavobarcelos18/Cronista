"""Shorts finalizados (Fase 9A): 9:16 1080x1920, legenda gravada, margens seguras e loudness (plano 6.6).

Entra um `ShortCandidate` (Fase 6D: janela de até 13 s, gancho nos 3 primeiros segundos) e sai um MP4 pronto,
sem nada do Studio do Resolve: reenquadramento, legenda (ASS) e loudness são do FFmpeg.

Reenquadramento 16:9 para 9:16 (plano 6.6), nos dois modos, sem facecam:
- `desfoque` (padrão): a gameplay inteira no centro, sobre ela mesma ampliada e desfocada (não perde nada);
- `recorte`: janela vertical da gameplay em torno de `focus_x`, ampliada (perde resolução e as bordas). O foco
  é fixo por enquanto: o seguidor de saliência (região de ação) não existe no banco e fica para depois.

A parte pura (legenda, layout, filtros, nome do arquivo) roda em `dev` sem FFmpeg. O executor `render_shorts`
chama o FFmpeg e só se confere com mídia real em `prod`. As margens seguras são valores de memória da
interface de YouTube Shorts/TikTok/Reels (⚠️ conferir na prática): topo e base livres, direita mais larga.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Literal

from cronista.config import Settings
from cronista.domain.frames import FPS
from cronista.finishing.brand import Visual
from cronista.finishing.render.atomic import render_to
from cronista.finishing.render.overlay import find_font
from cronista.finishing.render.video import filter_path
from cronista.ingest.ffmpeg import probe_media, run_ffmpeg
from cronista.pipeline.gpu import GpuGate, wait_until_free
from cronista.shorts.candidates import ShortCandidate

WIDTH, HEIGHT = 1080, 1920
Reframe = Literal["desfoque", "recorte"]


@dataclass(frozen=True)
class SafeZone:
    """Pixels do quadro 1080x1920 que a interface das plataformas cobre (título, botões, descrição)."""

    top: int = 250
    bottom: int = 450
    left: int = 60
    right: int = 140


@dataclass(frozen=True)
class ShortStyle:
    reframe: Reframe = "desfoque"
    focus_x: float = 0.5
    """Só no `recorte`: onde a janela vertical fica na gameplay (0 = esquerda, 1 = direita)."""
    words_per_caption: int = 3
    max_gap_s: float = 0.6
    """Pausa que fecha um grupo de legenda, mesmo com palavras sobrando."""
    font_size: int = 88
    outline: int = 7
    blur: int = 40
    background_dim: float = 0.2
    """Quanto o fundo desfocado escurece (0 a 1), para a gameplay no centro se destacar."""
    loudness_lufs: float = -14.0
    fade_out_s: float = 0.15
    """Corte suave no fim: ajuda o loop e evita estalo."""
    safe: SafeZone = SafeZone()


@dataclass(frozen=True)
class CaptionWord:
    start_frame: int
    end_frame: int
    text: str


@dataclass(frozen=True)
class Caption:
    """Um grupo de palavras, em segundos a partir do começo do Short."""

    start_s: float
    end_s: float
    words: tuple[tuple[float, float, str], ...]


# --- legenda ---------------------------------------------------------------------------------------------


def caption_groups(
    words: Sequence[CaptionWord], start_frame: int, end_frame: int, style: ShortStyle
) -> list[Caption]:
    """Palavras que cabem inteiras na janela, em grupos de `words_per_caption` (quebra em pausa longa)."""
    inside = sorted(
        (w for w in words if w.start_frame >= start_frame and w.end_frame <= end_frame and w.text.strip()),
        key=lambda w: w.start_frame,
    )
    groups: list[list[CaptionWord]] = []
    for w in inside:
        gap = style.max_gap_s * FPS
        if (
            not groups
            or len(groups[-1]) >= style.words_per_caption
            or w.start_frame - groups[-1][-1].end_frame > gap
        ):
            groups.append([])
        groups[-1].append(w)
    out: list[Caption] = []
    for n, group in enumerate(groups):
        nxt = groups[n + 1][0].start_frame if n + 1 < len(groups) else end_frame
        hold_end = min(group[-1].end_frame + round(0.15 * FPS), nxt, end_frame)
        spans = tuple(
            ((w.start_frame - start_frame) / FPS, (w.end_frame - start_frame) / FPS, w.text.strip())
            for w in group
        )
        out.append(Caption((group[0].start_frame - start_frame) / FPS, (hold_end - start_frame) / FPS, spans))
    return out


def ass_color(hex_color: str) -> str:
    """`#RRGGBB` → `&H00BBGGRR` (o ASS escreve a cor ao contrário)."""
    value = hex_color.lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        raise ValueError(f"cor inválida: {hex_color!r}")
    return f"&H00{value[4:6]}{value[2:4]}{value[0:2]}".upper()


def ass_time(seconds: float) -> str:
    """`H:MM:SS.cc` (centésimos, arredondados)."""
    centis = round(max(0.0, seconds) * 100)
    h, rest = divmod(centis, 360000)
    m, rest = divmod(rest, 6000)
    s, c = divmod(rest, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def ass_escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


@dataclass(frozen=True)
class Layout:
    caption_top: int
    """Linha (px) onde o bloco da legenda começa."""
    foreground: tuple[int, int, int] | None
    """`desfoque`: largura, altura e linha de topo da gameplay; `recorte`: nada."""


def layout(style: ShortStyle, src_w: int, src_h: int) -> Layout:
    """Onde a gameplay e a legenda ficam, sempre dentro das margens seguras."""
    block = round(style.font_size * 1.25 * 2)  # até duas linhas
    lowest_top = HEIGHT - style.safe.bottom - block
    if style.reframe == "recorte":
        return Layout(lowest_top, None)
    fg_h = round(WIDTH * src_h / src_w / 2) * 2
    gap = 48
    # gameplay + legenda formam um bloco só, centrado entre as margens seguras (não no quadro inteiro)
    area = HEIGHT - style.safe.top - style.safe.bottom
    fg_top = style.safe.top + max(0, (area - (fg_h + gap + block)) // 2)
    return Layout(min(fg_top + fg_h + gap, lowest_top), (WIDTH, fg_h, fg_top))


def build_ass(captions: Sequence[Caption], visual: Visual, style: ShortStyle, lay: Layout) -> str:
    """Arquivo ASS: cada palavra acende na cor de destaque enquanto é falada; o grupo inteiro fica visível."""
    pal = visual.palette
    margin_lr = max(style.safe.left, style.safe.right)
    head = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {WIDTH}\nPlayResY: {HEIGHT}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{ass_escape(visual.fonts.title)},{style.font_size},{ass_color(pal.text)},"
        f"{ass_color(pal.text)},{ass_color(pal.background)},&H00000000,-1,0,0,0,100,100,0,0,1,"
        f"{style.outline},0,8,{margin_lr},{margin_lr},{lay.caption_top},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    accent = ass_color(pal.accent)
    base = ass_color(pal.text)
    lines: list[str] = []
    for cap in captions:
        for n, (start, end, _) in enumerate(cap.words):
            stop = cap.words[n + 1][0] if n + 1 < len(cap.words) else max(cap.end_s, end)
            text = " ".join(
                (f"{{\\1c{accent}}}{ass_escape(t)}{{\\1c{base}}}" if i == n else ass_escape(t))
                for i, (_, _, t) in enumerate(cap.words)
            )
            lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(stop)},Default,,0,0,0,,{text}")
    return head + "\n".join(lines) + ("\n" if lines else "")


# --- filtros ---------------------------------------------------------------------------------------------


def _num(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def video_chain(style: ShortStyle, lay: Layout, ass_path: Path, fonts_dir: Path | None) -> str:
    """Grafo de filtros do vídeo, da entrada `[0:v]` à saída `[v]`: reenquadra, desenha a legenda, 60 fps."""
    ass = f"ass=filename='{filter_path(ass_path)}'"
    if fonts_dir is not None:
        ass += f":fontsdir='{filter_path(fonts_dir)}'"
    tail = f"{ass},fps={FPS},format=yuv420p[v]"
    if style.reframe == "recorte":
        fx = min(1.0, max(0.0, style.focus_x))
        crop_w = f"ih*{WIDTH}/{HEIGHT}"  # janela 9:16 na altura da gameplay
        return (
            f"[0:v]crop=w={crop_w}:h=ih:x='(iw-ow)*{_num(fx)}':y=0,"
            f"scale={WIDTH}:{HEIGHT}:flags=lanczos,setsar=1,{tail}"
        )
    assert lay.foreground is not None
    fg_w, _, fg_top = lay.foreground
    dim = _num(-style.background_dim)
    return (
        "[0:v]split=2[bg][fg];"
        f"[bg]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},"
        f"boxblur={style.blur}:5,eq=brightness={dim}[b];"
        f"[fg]scale={fg_w}:-2:flags=lanczos[f];"
        f"[b][f]overlay=(W-w)/2:{fg_top},setsar=1,{tail}"
    )


def audio_chain(style: ShortStyle, seconds: float) -> str:
    """Mix da faixa 1 normalizado ao alvo do canal, com corte suave no fim."""
    fade = min(style.fade_out_s, seconds / 4)
    return (
        f"loudnorm=I={_num(style.loudness_lufs)}:TP=-1.5:LRA=11,aresample=48000,"
        f"afade=t=out:st={seconds - fade:.3f}:d={fade:.3f}"
    )


def encoder_args(settings: Settings) -> list[str]:
    """Qualidade de entrega (acima da prévia): o Short é o produto final."""
    encoder = settings.preview_encoder
    if encoder.endswith("_nvenc"):
        return ["-c:v", encoder, "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0"]
    return ["-c:v", encoder, "-preset", "medium", "-crf", "18"]


def short_name(c: ShortCandidate, chain: str, ass: str, audio: str, encoder: list[str]) -> str:
    digest = hashlib.sha256("|".join([chain, ass, audio, *encoder]).encode()).hexdigest()[:10]
    return f"short-{c.file_id}-{c.start_frame}-{c.end_frame}-{digest}.mp4"


# --- render ----------------------------------------------------------------------------------------------


@dataclass
class ShortsRender:
    clips: dict[str, Path]
    """Nome do candidato (`<arquivo>-<quadro inicial>`) → MP4 pronto."""
    warnings: list[str]


def candidate_key(c: ShortCandidate) -> str:
    return f"{c.file_id}-{c.start_frame}"


def _encode(settings: Settings, c: ShortCandidate, master: Path, filters: str, audio: str, out: Path) -> None:
    seconds = (c.end_frame - c.start_frame) / FPS
    run_ffmpeg(
        settings,
        [
            "-ss", f"{c.start_frame / FPS:.6f}",
            "-t", f"{seconds:.6f}",
            "-i", str(master),
            "-filter_complex", filters,
            "-map", "[v]", "-map", "0:a:0",
            "-af", audio,
            *encoder_args(settings),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-r", str(FPS), "-movflags", "+faststart",
            str(out),
        ],
    )  # fmt: skip


def brand_fonts_dir(brand_dir: Path | None, visual: Visual) -> Path | None:
    """Pasta da primeira fonte versionada no brand kit (o libass acha a família por ela)."""
    if brand_dir is None:
        return None
    for relative in visual.fonts.files:
        candidate = brand_dir / relative
        if candidate.is_file():
            return candidate.parent
    return None


def render_shorts(
    candidates: Sequence[ShortCandidate],
    words_by_file: Mapping[int, Sequence[CaptionWord]],
    masters: Mapping[int, Path],
    visual: Visual,
    out_dir: Path,
    settings: Settings,
    *,
    style: ShortStyle | None = None,
    brand_dir: Path | None = None,
    gate: GpuGate | None = None,
) -> ShortsRender:
    """Um MP4 por candidato; reaproveita o que existe (nome com hash do filtro, da legenda e do encoder)."""
    style = style or ShortStyle()
    out_dir.mkdir(parents=True, exist_ok=True)
    result = ShortsRender({}, [])
    encoder = encoder_args(settings)
    fonts_dir = brand_fonts_dir(brand_dir, visual)
    if find_font(brand_dir, visual) is None and fonts_dir is None:
        result.warnings.append("nenhuma fonte do brand kit: a legenda usa a fonte padrão do sistema")
    for c in candidates:
        master = masters.get(c.file_id)
        if master is None:
            result.warnings.append(f"{candidate_key(c)}: gravação {c.file_id} sem arquivo mestre; ignorado")
            continue
        probe = probe_media(settings, master)
        if not probe.width or not probe.height:
            result.warnings.append(
                f"{candidate_key(c)}: não consegui ler o tamanho de {master.name}; ignorado"
            )
            continue
        captions = caption_groups(words_by_file.get(c.file_id, ()), c.start_frame, c.end_frame, style)
        if not captions:
            result.warnings.append(
                f"{candidate_key(c)}: sem palavras do Whisper na janela; Short sem legenda"
            )
        lay = layout(style, probe.width, probe.height)
        ass_text = build_ass(captions, visual, style, lay)
        ass_path = out_dir / f"short-{c.file_id}-{c.start_frame}.ass"
        ass_path.write_text(ass_text, encoding="utf-8")
        filters = video_chain(style, lay, ass_path, fonts_dir)
        audio = audio_chain(style, (c.end_frame - c.start_frame) / FPS)
        target = out_dir / short_name(c, filters, ass_text, audio, encoder)
        if not target.is_file() or target.stat().st_size == 0:
            if gate is not None:  # a GPU é a mesma do OBS e do jogo
                wait_until_free(gate, settings.gpu_poll_seconds, etapa="short", arquivo=target.name)
            render_to(target, partial(_encode, settings, c, master, filters, audio))
        result.clips[candidate_key(c)] = target
    return result
