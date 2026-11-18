"""Camada de acabamento no FCPXML (Fase 8D): V2, V4, A4 e A5 como clipes conectados ao corte de V1.

- zoom e shake (V2, lane 1): `editavel` = cópia do corte com keyframes de escala/posição (editáveis);
  `renderizado` = o MP4 pronto do FFmpeg.
- contador de mortes (V4, lane 3): `editavel` = título "Mortes: N"; `renderizado` = MOV com alfa.
- SFX e SFX de meme (A5, lane -5): o arquivo da biblioteca com o ganho do plano (sem render).
- música (A4, lane -4): `editavel` = arquivo cortado nos compassos, volume fixo; `renderizado` = o stem A4
  com ducking, que entra por `ExportMedia.stems`, como os outros stems.

`sugerir` nunca entra aqui (vira marcador) e tudo fica **acima** do original: desligar a trilha desfaz.
⚠️ Ainda não provado no Resolve (plano 6.5): se ele respeita os keyframes de `adjust-transform` (e a unidade de
`position`, aqui em % da altura) e as lanes 1, 3, -4 e -5 sem trilhas intermediárias.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from cronista.assembly.plan import LIVE_MODES, EditItem, Track
from cronista.domain.frames import fcpxml_time
from cronista.finishing.effects import EffectKind, EffectMode
from cronista.finishing.plan import FinishItem, FinishPlan
from cronista.finishing.render.audio import MUSIC_BED_DB
from cronista.finishing.render.video import HEIGHT, shake_state, zoom_curve

LANE_V2, LANE_V4 = 1, 3
LANE_MUSIC, LANE_SFX = -4, -5
APPLIED = frozenset({EffectMode.EDITAVEL, EffectMode.RENDERIZADO})
ZOOM_KEY_STEP = 5
"""Um keyframe de zoom a cada 5 quadros (a curva é suave); o tremor leva um por quadro."""


@dataclass(frozen=True)
class AudioFile:
    path: Path
    frames: int


@dataclass
class FinishLayers:
    """O que o FCPXML precisa além do plano: renderizados, áudios da biblioteca e textos editáveis."""

    plan: FinishPlan
    rendered: Mapping[str, Path] = field(default_factory=dict)
    """`id` do item → clipe pronto (MP4 da V2, MOV com alfa da V4)."""
    rendered_frames: Mapping[str, int] = field(default_factory=dict)
    """Duração dos clipes renderizados, em quadros (o FCPXML precisa dela no `asset`)."""
    audio: Mapping[str, AudioFile] = field(default_factory=dict)
    """`id` da biblioteca → arquivo e duração."""
    texts: Mapping[str, str] = field(default_factory=dict)
    """`id` do item → texto do título editável (contador de mortes)."""
    font: str = "Helvetica"
    font_size: int = 72
    font_color: str = "1 1 1 1"


AssetFn = Callable[[Path, int, bool], str]
"""`asset(path, frames, video=...)` do `render_plan_fcpxml`: devolve o `id` do recurso."""


def _inside(cut: EditItem, item: FinishItem) -> bool:
    return cut.timeline_start <= item.start < cut.timeline_end


def add_finish_clips(
    parent: ET.Element,
    cut: EditItem,
    parent_start: int,
    layers: FinishLayers,
    asset: AssetFn,
    title_count: list[int],
) -> None:
    """Pendura em `parent` (o clipe de V1 de `cut`) tudo do acabamento que cai dentro dele.

    `parent_start` é onde o tempo do pai começa (quadro de origem; 0 no timelapse): o deslocamento de um
    conectado conta nesse tempo, como nos stems.
    """

    def offset_of(frame: int) -> str:
        return fcpxml_time(parent_start + frame - cut.timeline_start)

    live = cut.track == Track.V1 and cut.mode in LIVE_MODES and cut.speed == 1
    ordered = sorted(layers.plan.items, key=lambda i: (i.start, i.id))
    for item in ordered:
        if item.mode not in APPLIED:
            continue
        if item.kind in (EffectKind.ZOOM, EffectKind.SHAKE) and live and _inside(cut, item):
            _video_effect(parent, cut, item, parent_start, layers, asset, offset_of(item.start))
        elif item.kind == EffectKind.CONTADOR_MORTES and _inside(cut, item):
            _counter(parent, cut, item, layers, asset, offset_of(item.start), title_count)
        elif item.kind in (EffectKind.SFX, EffectKind.SFX_MEME) and _inside(cut, item):
            _sfx(parent, cut, item, layers, asset, offset_of(item.start))
        elif item.kind == EffectKind.MUSICA and item.mode == EffectMode.EDITAVEL:
            _music(parent, cut, item, layers, asset, offset_of)


def _frames_in(cut: EditItem, item: FinishItem, frames: int) -> int:
    return min(frames, cut.timeline_end - item.start)


def _video_effect(
    parent: ET.Element,
    cut: EditItem,
    item: FinishItem,
    parent_start: int,
    layers: FinishLayers,
    asset: AssetFn,
    offset: str,
) -> None:
    frames = _frames_in(cut, item, item.frames)
    if frames < 2:
        return
    label = f"{item.kind.value}|{item.id}"
    if item.mode == EffectMode.RENDERIZADO:
        path = layers.rendered.get(item.id)
        if path is None:
            return  # o render avisou o motivo
        ET.SubElement(
            parent,
            "asset-clip",
            ref=asset(path, layers.rendered_frames.get(item.id, item.frames), True),
            lane=str(LANE_V2),
            name=label,
            offset=offset,
            start="0s",
            duration=fcpxml_time(frames),
            format="r1",
        )
        return
    start = parent_start + item.start - cut.timeline_start
    clip = ET.SubElement(
        parent,
        "asset-clip",
        ref=parent.get("ref", ""),
        lane=str(LANE_V2),
        name=label,
        offset=offset,
        start=fcpxml_time(start),
        duration=fcpxml_time(frames),
        format="r1",
    )
    _keyframes(clip, item, start, frames)


def _keyframes(clip: ET.Element, item: FinishItem, start: int, frames: int) -> None:
    """Escala (e posição, no tremor) em keyframes; o primeiro e o último valem o enquadramento original."""
    transform = ET.SubElement(clip, "adjust-transform")
    scale_anim = ET.SubElement(ET.SubElement(transform, "param", name="scale"), "keyframeAnimation")
    if item.kind == EffectKind.ZOOM:
        peak = float(item.params.get("escala", 1.1))
        easing = str(item.params.get("easing", "ease_in_out"))
        ks = sorted({*range(0, frames, ZOOM_KEY_STEP), frames - 1})
        for k in ks:
            s = 1.0 + (peak - 1.0) * zoom_curve(k / (frames - 1), easing)
            ET.SubElement(scale_anim, "keyframe", time=fcpxml_time(start + k), value=f"{s:.5f} {s:.5f}")
        return
    amplitude = float(item.params.get("amplitude_px", 8.0))
    position_anim = ET.SubElement(ET.SubElement(transform, "param", name="position"), "keyframeAnimation")
    for k in range(frames):
        s, dx, dy = shake_state(amplitude, k, frames)
        ET.SubElement(scale_anim, "keyframe", time=fcpxml_time(start + k), value=f"{s:.5f} {s:.5f}")
        # Posição em % da altura do quadro (unidade do FCPXML; a conferir no Resolve), y para cima.
        ET.SubElement(
            position_anim,
            "keyframe",
            time=fcpxml_time(start + k),
            value=f"{dx * 100 / HEIGHT:.4f} {-dy * 100 / HEIGHT:.4f}",
        )


def _counter(
    parent: ET.Element,
    cut: EditItem,
    item: FinishItem,
    layers: FinishLayers,
    asset: AssetFn,
    offset: str,
    title_count: list[int],
) -> None:
    frames = _frames_in(cut, item, item.frames)
    if frames < 2:
        return
    if item.mode == EffectMode.RENDERIZADO:
        path = layers.rendered.get(item.id)
        if path is None:
            return
        ET.SubElement(
            parent,
            "asset-clip",
            ref=asset(path, layers.rendered_frames.get(item.id, item.frames), True),
            lane=str(LANE_V4),
            name=f"contador|{item.id}",
            offset=offset,
            start="0s",
            duration=fcpxml_time(frames),
            format="r1",
        )
        return
    text = layers.texts.get(item.id)
    if text is None:
        return
    title_count[0] += 1
    style = f"fx{title_count[0]}"
    title = ET.SubElement(
        parent,
        "title",
        ref="r2",
        lane=str(LANE_V4),
        name=f"contador|{item.id}",
        offset=offset,
        start="0s",
        duration=fcpxml_time(frames),
    )
    ET.SubElement(ET.SubElement(title, "text"), "text-style", ref=style).text = text
    definition = ET.SubElement(title, "text-style-def", id=style)
    ET.SubElement(
        definition,
        "text-style",
        font=layers.font,
        fontSize=str(layers.font_size),
        fontColor=layers.font_color,
    )


def _sfx(
    parent: ET.Element, cut: EditItem, item: FinishItem, layers: FinishLayers, asset: AssetFn, offset: str
) -> None:
    audio = layers.audio.get(item.asset_id or "")
    if audio is None:
        return
    frames = _frames_in(cut, item, audio.frames)
    if frames < 1:
        return
    clip = ET.SubElement(
        parent,
        "asset-clip",
        ref=asset(audio.path, audio.frames, False),
        lane=str(LANE_SFX),
        name=f"{item.kind.value}|{item.asset_id}",
        offset=offset,
        start="0s",
        duration=fcpxml_time(frames),
    )
    ET.SubElement(clip, "adjust-volume", amount=f"{float(item.params.get('ganho_db', -9.0)):g}dB")


def _music(
    parent: ET.Element,
    cut: EditItem,
    item: FinishItem,
    layers: FinishLayers,
    asset: AssetFn,
    offset_of: Callable[[int], str],
) -> None:
    """Música editável: a parte da trilha que cai neste corte (a trilha atravessa vários cortes)."""
    audio = layers.audio.get(item.asset_id or "")
    seg_start, seg_end = max(item.start, cut.timeline_start), min(item.end, cut.timeline_end)
    if audio is None or seg_end - seg_start < 1 or seg_start - item.start >= audio.frames:
        return  # sem arquivo, fora deste corte, ou a trilha já acabou (arquivo mais curto que o capítulo)
    clip = ET.SubElement(
        parent,
        "asset-clip",
        ref=asset(audio.path, audio.frames, False),
        lane=str(LANE_MUSIC),
        name=f"musica|{item.asset_id}",
        offset=offset_of(seg_start),
        start=fcpxml_time(seg_start - item.start),
        duration=fcpxml_time(min(seg_end - seg_start, audio.frames - (seg_start - item.start))),
    )
    ET.SubElement(clip, "adjust-volume", amount=f"{MUSIC_BED_DB:g}dB")
