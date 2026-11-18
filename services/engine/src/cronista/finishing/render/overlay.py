"""Overlay do contador de mortes (Fase 8C): ProRes 4444 com alfa, para a trilha V4, feito só com FFmpeg.

O plano (8C) previa templates Remotion; a licença dele para o uso do criador ficou sem verificação (histórico
§45) e este overlay é só texto com caixa, então sai do `drawtext` do FFmpeg, sem dependência nova. Se um dia o
Remotion for adotado, o contrato (um MOV com alfa por item do plano) não muda.

O número é o da morte no vídeo (`ordem` do plano), nunca o do dia: cartelas de dia ficam em título editável.
A parte pura (texto, posição, filtro) é testável sem FFmpeg; o alfa só se confirma em `prod`, importando o
MOV no Resolve (a receita de ProRes 4444 com alfa é a do kit do spike, `devtools/resolve_kit.py`).
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from cronista.config import Settings
from cronista.domain.frames import FPS
from cronista.finishing.brand import DeathCounter, Visual
from cronista.finishing.effects import EffectKind, EffectMode
from cronista.finishing.plan import FinishItem, FinishPlan
from cronista.finishing.render.atomic import render_to
from cronista.finishing.render.video import HEIGHT, WIDTH, filter_path
from cronista.ingest.ffmpeg import run_ffmpeg
from cronista.pipeline.gpu import GpuGate, wait_until_free

MARGIN_PX = 80
BOX_PAD_PX = 24
FONT_SIZE = 72
FADE_S = 0.2


def _system_fonts() -> tuple[str, ...]:
    """Fontes em negrito do sistema. No Windows a pasta vem de `WINDIR` (sem caminho fixo no código)."""
    windir = os.environ.get("WINDIR") or os.environ.get("SYSTEMROOT")
    windows = (
        tuple(str(Path(windir) / "Fonts" / n) for n in ("arialbd.ttf", "segoeuib.ttf")) if windir else ()
    )
    return (
        *windows,
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    )


SYSTEM_FONTS = _system_fonts()

_DRAWTEXT_SPECIAL = re.compile(r"([\\:%])")


def fmt_num(value: float) -> str:
    """Número para a sintaxe de filtro do FFmpeg: até 4 casas, sem zeros sobrando."""
    return f"{value:.4f}".rstrip("0").rstrip(".")


def drawtext_escape(text: str) -> str:
    """Texto dentro de `text='...'` do drawtext: barra, dois-pontos e `%` ganham barra na frente.

    Dentro de aspas simples o FFmpeg não aceita aspa escapada: a aspa do texto fecha a citação, entra escapada
    nos dois níveis do parser (três barras e a aspa) e reabre a citação.
    """
    return _DRAWTEXT_SPECIAL.sub(r"\\\1", text).replace("'", "'\\\\\\''")


def ffmpeg_color(hex_color: str, alpha: float = 1.0) -> str:
    """`#RRGGBB` → `0xRRGGBB@alpha` (sintaxe de cor do FFmpeg)."""
    value = hex_color.lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        raise ValueError(f"cor inválida: {hex_color!r}")
    return f"0x{value.upper()}" + (f"@{alpha:g}" if alpha < 1 else "")


def find_font(brand_dir: Path | None, visual: Visual, system: Iterable[str] = SYSTEM_FONTS) -> Path | None:
    """Fonte do brand kit (arquivo versionado) ou a primeira fonte do sistema que existir."""
    if brand_dir is not None:
        for relative in visual.fonts.files:
            candidate = brand_dir / relative
            if candidate.is_file():
                return candidate
    return next((Path(p) for p in system if Path(p).is_file()), None)


def counter_text(counter: DeathCounter, order: int) -> str:
    return counter.template.replace("{n}", str(order))


def counter_position(position: str) -> tuple[str, str]:
    """Expressões `x`, `y` do drawtext para o canto escolhido (a caixa ocupa `BOX_PAD_PX` a mais)."""
    pad = MARGIN_PX + BOX_PAD_PX
    horizontal = f"{pad}" if position.endswith("esquerda") else f"w-text_w-{pad}"
    vertical = f"{pad}" if position.startswith("topo") else f"h-text_h-{pad}"
    return horizontal, vertical


def counter_filter(
    text: str,
    frames: int,
    visual: Visual,
    position: str,
    font: Path,
    *,
    width: int = WIDTH,
    height: int = HEIGHT,
) -> str:
    """Fundo transparente RGBA + texto com caixa e fade de 0,2 s nas pontas, alfa até o ProRes 4444."""
    if frames < 2:
        raise ValueError("o overlay precisa de pelo menos 2 quadros")
    seconds = frames / FPS
    fade = min(FADE_S, seconds / 4)
    x, y = counter_position(position)
    drawtext = (
        f"drawtext=fontfile='{filter_path(font)}':text='{drawtext_escape(text)}':fontsize={FONT_SIZE}"
        f":fontcolor={ffmpeg_color(visual.palette.text)}:x={x}:y={y}"
        f":box=1:boxcolor={ffmpeg_color(visual.palette.background, 0.65)}:boxborderw={BOX_PAD_PX}"
    )
    return (
        f"color=c=black@0.0:s={width}x{height}:r={FPS}:d={seconds:.6f},format=rgba,{drawtext},"
        f"fade=t=in:st=0:d={fade:.3f}:alpha=1,fade=t=out:st={seconds - fade:.3f}:d={fade:.3f}:alpha=1,"
        "format=yuva444p10le"
    )


@dataclass
class OverlayRender:
    clips: dict[str, Path]
    """`id` do item do plano → MOV com alfa para a V4."""
    warnings: list[str]


def _encode(settings: Settings, chain: str, frames: int, out: Path) -> None:
    run_ffmpeg(
        settings,
        [
            "-f", "lavfi", "-i", chain,
            "-frames:v", str(frames),
            "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
            str(out),
        ],
    )  # fmt: skip


def render_overlays(
    finish: FinishPlan,
    visual: Visual,
    brand_dir: Path | None,
    out_dir: Path,
    settings: Settings,
    gate: GpuGate | None = None,
    system_fonts: Iterable[str] = SYSTEM_FONTS,
) -> OverlayRender:
    """Um MOV por contador de mortes em modo `renderizado`. Reaproveita o que já existe (hash do filtro)."""
    result = OverlayRender({}, [])
    todo = [
        i
        for i in sorted(finish.items, key=lambda i: (i.start, i.id))
        if i.kind == EffectKind.CONTADOR_MORTES and i.mode == EffectMode.RENDERIZADO
    ]
    if not todo:
        return result
    font = find_font(brand_dir, visual, system_fonts)
    if font is None:
        result.warnings.append(
            "contador de mortes: nenhuma fonte encontrada (declare `fonts.files` no brand kit); sem overlay"
        )
        return result
    out_dir.mkdir(parents=True, exist_ok=True)
    for item in todo:
        chain = counter_filter(
            counter_text(visual.death_counter, int(item.params.get("ordem", 0))),
            item.frames,
            visual,
            visual.death_counter.position,
            font,
        )
        target = out_dir / overlay_name(item, chain)
        if not target.is_file() or target.stat().st_size == 0:
            if gate is not None:
                wait_until_free(gate, settings.gpu_poll_seconds, etapa="overlay", arquivo=target.name)
            render_to(target, partial(_encode, settings, chain, item.frames))
        result.clips[item.id] = target
    return result


def overlay_name(item: FinishItem, chain: str) -> str:
    digest = hashlib.sha256(chain.encode()).hexdigest()[:10]
    return f"ov-{item.kind.value}-{item.params.get('ordem', 0)}-{item.frames}-{digest}.mov"
