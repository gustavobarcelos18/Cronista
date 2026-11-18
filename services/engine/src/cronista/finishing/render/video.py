"""Zoom, shake e LUT com FFmpeg (Fase 8C): clipes para a trilha V2, logo acima do original (plano 6.3).

Nada do Studio do Resolve (sem Speed Warp, Magic Mask, Super Scale): tudo sai de filtros do FFmpeg.
Cada clipe de V2 **começa e termina com o enquadramento original** (escala 1, sem deslocamento), então a
emenda com o V1 por baixo não aparece e desligar a trilha V2 devolve a gravação intacta.

A parte pura (curvas, filtros, janela de origem) não chama o FFmpeg e é testável em `dev`. O executor
`render_video_effects` chama o FFmpeg e só foi exercitado com o FFmpeg real em `prod`.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from cronista.assembly.plan import LIVE_MODES, EditItem, EditPlan, Track
from cronista.config import Settings
from cronista.domain.frames import FPS
from cronista.finishing.effects import EffectKind, EffectMode
from cronista.finishing.plan import FinishItem, FinishPlan
from cronista.finishing.render.atomic import render_to
from cronista.ingest.ffmpeg import run_ffmpeg
from cronista.pipeline.gpu import GpuGate, wait_until_free
from cronista.preview.service import video_args

WIDTH, HEIGHT = 1920, 1080
UPSCALE = 2
"""A imagem sobe 2x antes do `zoompan`: sem isso o enquadramento treme em passos de 1 pixel."""

SHAKE_HZ = (12.0, 15.0)
"""Frequências (x, y) do tremor; diferentes para o movimento não virar uma diagonal."""
SHAKE_GROW = 1.15
"""Folga de 15 % na ampliação do tremor, para o deslocamento nunca mostrar a borda."""

RENDERED_KINDS = frozenset({EffectKind.ZOOM, EffectKind.SHAKE})


# --- curvas (Python espelha a expressão do FFmpeg; os testes comparam as duas) ---------------------------


def zoom_curve(progress: float, easing: str = "ease_in_out") -> float:
    """0 → 1 → 0 no trecho (`progress` de 0 a 1): sobe até o pico no meio e volta ao enquadramento."""
    p = min(1.0, max(0.0, progress))
    if easing == "linear":
        return 1.0 - abs(2.0 * p - 1.0)
    return math.sin(math.pi * p) ** 2


def zoom_expr(easing: str) -> str:
    """A mesma curva em sintaxe de expressão do FFmpeg, com `{n1}` = último quadro de saída (`on`)."""
    if easing == "linear":
        return "(1-abs(2*on/{n1}-1))"
    return "pow(sin(PI*on/{n1}),2)"


def shake_envelope(progress: float) -> float:
    """0 no início, sobe rápido (10 % do trecho) e some até 0 no fim: a pancada que se acomoda."""
    p = min(1.0, max(0.0, progress))
    return (1.0 - p) * min(1.0, 10.0 * p)


# --- filtros ---------------------------------------------------------------------------------------------


def shake_state(amplitude_px: float, k: int, frames: int, width: int = WIDTH) -> tuple[float, float, float]:
    """Escala e deslocamento (px de saída) do tremor no quadro `k`: o mesmo movimento do filtro, em Python.

    Serve aos keyframes do modo `editavel` (FCPXML), para o tremor sair igual ao renderizado.
    """
    n1 = max(1, frames - 1)
    env = shake_envelope(k / n1)
    scale = 1.0 + SHAKE_GROW * 2 * amplitude_px / width * env
    hx, hy = SHAKE_HZ
    dx = amplitude_px * env * math.sin(2 * math.pi * hx * k / FPS)
    dy = amplitude_px * env * math.sin(2 * math.pi * hy * k / FPS + 1.3)
    return scale, dx, dy


def _num(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def zoom_filter(
    scale: float,
    frames: int,
    *,
    easing: str = "ease_in_out",
    focus: tuple[float, float] = (0.5, 0.5),
    width: int = WIDTH,
    height: int = HEIGHT,
) -> str:
    """Punch-in até `scale` (1.15 = 15 %) centrado em `focus` (0 a 1 da imagem), `frames` quadros a 60 fps."""
    if scale < 1.0:
        raise ValueError("a escala do zoom precisa ser >= 1")
    if frames < 2:
        raise ValueError("o zoom precisa de pelo menos 2 quadros")
    n1 = frames - 1
    curve = zoom_expr(easing).replace("{n1}", str(n1))
    fx, fy = (min(1.0, max(0.0, v)) for v in focus)
    return (
        f"scale={width * UPSCALE}:{height * UPSCALE}:flags=lanczos,"
        f"zoompan=z='1+({_num(scale - 1)})*{curve}'"
        f":x='(iw-iw/zoom)*{_num(fx)}':y='(ih-ih/zoom)*{_num(fy)}'"
        f":d=1:s={width}x{height}:fps={FPS}"
    )


def shake_filter(
    amplitude_px: float,
    frames: int,
    *,
    width: int = WIDTH,
    height: int = HEIGHT,
) -> str:
    """Tremor de até `amplitude_px` pixels de saída, com a imagem ampliada só o necessário e voltando a 1.

    A ampliação cresce e some junto com o tremor (zoom ≈ 1 + 2·A/L·envelope), para o primeiro e o último
    quadro serem idênticos ao original. Os deslocamentos usam `on/60` como relógio.
    """
    if amplitude_px <= 0:
        raise ValueError("a amplitude do tremor precisa ser > 0")
    if frames < 2:
        raise ValueError("o tremor precisa de pelo menos 2 quadros")
    n1 = frames - 1
    env = f"((1-on/{n1})*min(1,10*on/{n1}))"
    grow = SHAKE_GROW * 2 * amplitude_px / width
    hx, hy = SHAKE_HZ
    shift = amplitude_px * UPSCALE
    return (
        f"scale={width * UPSCALE}:{height * UPSCALE}:flags=lanczos,"
        f"zoompan=z='1+{_num(grow)}*{env}'"
        f":x='(iw-iw/zoom)/2+{_num(shift)}*{env}*sin(2*PI*{_num(hx)}*on/{FPS})'"
        f":y='(ih-ih/zoom)/2+{_num(shift)}*{env}*sin(2*PI*{_num(hy)}*on/{FPS}+1.3)'"
        f":d=1:s={width}x{height}:fps={FPS}"
    )


_SPECIAL = re.compile(r"([\\:',\[\];=])")


def filter_path(path: Path) -> str:
    """Caminho dentro de um filtro do FFmpeg: barras normais e `: ' , [ ] ; =` escapados (cabe no Windows)."""
    return _SPECIAL.sub(r"\\\1", path.as_posix())


def lut_filter(path: Path) -> str:
    """`.cube` pelo `lut3d` (nativo do FFmpeg; nada do Studio)."""
    return f"lut3d=file='{filter_path(path)}'"


def effect_filter(item: FinishItem, frames: int) -> str:
    """Cadeia de filtros de um item de zoom ou shake do plano."""
    if item.kind == EffectKind.ZOOM:
        focus = (float(item.params.get("foco_x", 0.5)), float(item.params.get("foco_y", 0.5)))
        return zoom_filter(
            float(item.params.get("escala", 1.1)),
            frames,
            easing=str(item.params.get("easing", "ease_in_out")),
            focus=focus,
        )
    if item.kind == EffectKind.SHAKE:
        return shake_filter(float(item.params.get("amplitude_px", 8.0)), frames)
    raise ValueError(f"{item.kind.value} não é um efeito de vídeo desta etapa")


# --- janela de origem ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceWindow:
    """Trecho da gravação original que fica sob o efeito: `frames` quadros a partir de `in_frame`."""

    file_id: int
    in_frame: int
    frames: int


def source_window(plan: EditPlan, item: FinishItem) -> SourceWindow | None:
    """Acha o corte de V1 sob o efeito. Só gameplay ao vivo em velocidade 1; o que passa do corte é aparado.

    Devolve `None` quando não há corte ao vivo sob o início do efeito (timelapse, B-roll ou vazio).
    """
    for cut in _live_cuts(plan.items):
        if cut.timeline_start <= item.start < cut.timeline_end:
            frames = min(item.frames, cut.timeline_end - item.start)
            if frames < 2:
                return None
            return SourceWindow(cut.file_id, cut.in_frame + (item.start - cut.timeline_start), frames)
    return None


def _live_cuts(items: list[EditItem]) -> list[EditItem]:
    return [i for i in items if i.track == Track.V1 and i.mode in LIVE_MODES and i.speed == 1]


# --- render ----------------------------------------------------------------------------------------------


@dataclass
class VideoRender:
    clips: dict[str, Path]
    """`id` do item do plano → MP4 pronto (60 fps, sem áudio) para a trilha V2."""
    warnings: list[str]


def clip_name(item: FinishItem, window: SourceWindow, chain: str, encoder_args: list[str]) -> str:
    digest = hashlib.sha256("|".join([chain, *encoder_args]).encode()).hexdigest()[:10]
    return f"fx-{item.kind.value}-{window.file_id}-{window.in_frame}-{window.frames}-{digest}.mp4"


def _encode(
    settings: Settings, window: SourceWindow, master: Path, chain: str, encoder: list[str], out: Path
) -> None:
    run_ffmpeg(
        settings,
        [
            "-ss", f"{window.in_frame / FPS:.6f}",
            "-t", f"{window.frames / FPS:.6f}",
            "-i", str(master),
            "-an",
            "-vf", f"{chain},format=yuv420p",
            "-r", str(FPS),
            "-frames:v", str(window.frames),
            *encoder,
            str(out),
        ],
    )  # fmt: skip


def render_video_effects(
    finish: FinishPlan,
    plan: EditPlan,
    masters: Mapping[int, Path],
    out_dir: Path,
    settings: Settings,
    gate: GpuGate | None = None,
) -> VideoRender:
    """Um MP4 por zoom/shake em modo `renderizado`. Reaproveita o que já existe (nome com hash do filtro)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    result = VideoRender({}, [])
    encoder = video_args(settings)
    for item in sorted(finish.items, key=lambda i: (i.start, i.id)):
        if item.kind not in RENDERED_KINDS or item.mode != EffectMode.RENDERIZADO:
            continue
        window = source_window(plan, item)
        if window is None:
            result.warnings.append(f"{item.id}: sem corte ao vivo sob o efeito; ignorado")
            continue
        master = masters.get(window.file_id)
        if master is None:
            result.warnings.append(f"{item.id}: gravação {window.file_id} sem arquivo mestre; ignorado")
            continue
        chain = effect_filter(item, window.frames)
        target = out_dir / clip_name(item, window, chain, encoder)
        if not target.is_file() or target.stat().st_size == 0:
            if gate is not None:  # a GPU é a mesma do OBS e do jogo
                wait_until_free(gate, settings.gpu_poll_seconds, etapa="efeito", arquivo=target.name)
            render_to(target, partial(_encode, settings, window, master, chain, encoder))
        result.clips[item.id] = target
    if any(i.kind == EffectKind.COR_LUT and i.mode == EffectMode.RENDERIZADO for i in finish.items):
        result.warnings.append(
            "LUT em modo renderizado ainda não é gerado (a V1 por baixo ficaria sem cor): use o modo editável"
        )
    return result
