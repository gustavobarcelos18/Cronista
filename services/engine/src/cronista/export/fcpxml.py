"""FCPXML 1.9 escrito à mão a partir da timeline OTIO, mais validação estrutural.

O adaptador `fcpx_xml` do OTIO (spike da 1B, histórico §30) gerou um arquivo que o Resolve 21.2 recusou
(sem `<library>`) e depois travou na importação (2026-11-16, histórico §39). Por isso o app escreve o FCPXML
no mesmo desenho dos arquivos do kit (`devtools/resolve_kit.py`), que o Resolve importa:
`library > event > project`, `asset` com `src`, um `asset-clip` por trecho na V1 e o áudio do jogo (lane -1)
e do microfone (lane -2) como `asset-clip` conectados. Todo tempo é um número inteiro de quadros de 1/60 s.
Não existe DTD oficial offline: `check_fcpxml` confere o que dá para provar (referências, grade de quadros,
duração da sequência, lanes). A validação de verdade é a importação no Resolve (1C).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from fractions import Fraction

import opentimelineio as otio

from cronista.domain.frames import FPS, fcpxml_time
from cronista.export.fcpxml_base import add_asset, new_skeleton, serialize

_TIME_ATTRS = ("offset", "duration", "start")


def render_fcpxml(timeline: otio.schema.Timeline) -> str:
    """V1 vira o `spine`; cada trilha de áudio seguinte vira a lane -1, -2... do clipe de mesmo índice."""
    video = next(t for t in timeline.tracks if t.kind == otio.schema.TrackKind.Video)
    audio = [t for t in timeline.tracks if t.kind == otio.schema.TrackKind.Audio]

    skeleton = new_skeleton(timeline.name or "sessao")
    resources, sequence, spine = skeleton.resources, skeleton.sequence, skeleton.spine
    ids: dict[str, str] = {}

    def asset_id(clip: otio.schema.Clip, is_video: bool) -> str:
        url = clip.media_reference.target_url
        if url not in ids:
            ids[url] = f"r{len(ids) + 2}"
            name = clip.media_reference.name or url.rsplit("/", 1)[-1]
            frames = int(clip.media_reference.available_range.duration.value)
            add_asset(resources, ids[url], name, url, frames, video=is_video)
        return ids[url]

    cursor = 0
    for index, clip in enumerate(video):
        rng = clip.source_range
        start, duration = round(rng.start_time.value), round(rng.duration.value)
        parent = ET.SubElement(
            spine,
            "asset-clip",
            ref=asset_id(clip, True),
            name=clip.name,
            offset=fcpxml_time(cursor),
            start=fcpxml_time(start),
            duration=fcpxml_time(duration),
            format="r1",
            tcFormat="NDF",
        )
        for lane, track in enumerate(audio, start=1):
            if index >= len(track):
                continue
            child = track[index]
            # O deslocamento de um clipe conectado conta no tempo do pai, que começa em `start`.
            ET.SubElement(
                parent,
                "asset-clip",
                ref=asset_id(child, False),
                lane=str(-lane),
                name=child.name,
                offset=fcpxml_time(start),
                start=fcpxml_time(start),
                duration=fcpxml_time(duration),
            )
        cursor += duration
    sequence.set("duration", fcpxml_time(cursor))

    return serialize(skeleton.root)


def _parse_time(text: str) -> Fraction | None:
    """`"5/1s"`, `"10s"` ou `"1/60s"` → segundos como fração exata; None se não for um tempo FCPXML."""
    if not text.endswith("s"):
        return None
    try:
        return Fraction(text[:-1])
    except (ValueError, ZeroDivisionError):
        return None


def check_fcpxml(xml: str) -> list[str]:
    """Problemas estruturais encontrados (lista vazia = passou)."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        return [f"XML mal formado: {exc}"]

    problems: list[str] = []
    if root.tag != "fcpxml" or not root.get("version"):
        problems.append("raiz deve ser <fcpxml version=...>")
    resources = root.find("resources")
    if resources is None:
        return [*problems, "falta <resources>"]

    ids = {e.get("id") for e in root.iter() if e.get("id")}  # inclui os ids de dentro do título
    formats = resources.findall("format")
    if not formats:
        problems.append("falta <format> em <resources>")
    for fmt in formats:
        if _parse_time(fmt.get("frameDuration", "")) != Fraction(1, FPS):
            problems.append(f"format {fmt.get('id')}: frameDuration deve ser 1/{FPS}s (60 fps exatos)")

    for element in root.iter():
        ref = element.get("ref")
        if ref is not None and ref not in ids:
            problems.append(f"<{element.tag}> aponta para ref '{ref}' que não está em <resources>")
        fmt_ref = element.get("format")
        if fmt_ref is not None and fmt_ref not in ids:
            problems.append(f"<{element.tag}> aponta para format '{fmt_ref}' inexistente")
        for attr in _TIME_ATTRS:
            raw = element.get(attr)
            if raw is None:
                continue
            seconds = _parse_time(raw)
            if seconds is None:
                problems.append(f"<{element.tag}>: {attr}='{raw}' não é um tempo FCPXML")
            elif (seconds * FPS).denominator != 1:
                problems.append(f"<{element.tag}>: {attr}='{raw}' fora da grade de {FPS} quadros/s")

    if any(child.tag == "asset-clip" for child in root):
        problems.append("<asset-clip> solto na raiz do <fcpxml>")
    if root.find("library/event/project/sequence") is None:
        problems.append(
            "a sequência precisa estar em <library><event><project> (o Resolve recusa sem <library>)"
        )

    sequences = list(root.iter("sequence"))
    if not sequences:
        problems.append("falta <sequence>")
    for sequence in sequences:
        spine = sequence.find("spine")
        if spine is None:
            problems.append("<sequence> sem <spine>")
            continue
        total = sum((_parse_time(c.get("duration", "")) or Fraction(0) for c in spine), Fraction(0))
        declared = _parse_time(sequence.get("duration", ""))
        if declared != total:
            problems.append(f"duração da sequência {sequence.get('duration')} ≠ soma dos clipes {total}s")
        lanes = {c.get("lane") for c in spine.iter() if c.get("lane")}
        if not {"-1", "-2"} <= lanes:
            problems.append("faltam as lanes de áudio -1 (A1, jogo) e -2 (A2, microfone)")
    return problems
