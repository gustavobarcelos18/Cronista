"""Pedaços comuns dos escritores de FCPXML: raiz, `resources`, `library`, `asset` e serialização.

Os dois escritores (`fcpxml.py`, da timeline OTIO da Fase 1, e `montagem.py`, do plano de montagem) montam o
mesmo esqueleto `library > event > project > sequence > spine`, no desenho que o Resolve importa (§39).
Aqui fica só o que é igual: quadro de 60 fps, nome do formato, atributos de `asset` e o cabeçalho XML.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

from cronista.domain.frames import FPS, fcpxml_time

WIDTH, HEIGHT = 1920, 1080
XML_HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n\n'
FORMAT_ID = "r1"


@dataclass(frozen=True)
class FcpxmlSkeleton:
    root: ET.Element
    resources: ET.Element
    sequence: ET.Element
    spine: ET.Element


def new_skeleton(project_name: str, **sequence_attrs: str) -> FcpxmlSkeleton:
    """Esqueleto vazio: formato 1920x1080 a 60 fps (`r1`), biblioteca, evento, projeto e `spine`."""
    root = ET.Element("fcpxml", version="1.9")
    resources = ET.SubElement(root, "resources")
    ET.SubElement(
        resources,
        "format",
        id=FORMAT_ID,
        name=f"FFVideoFormat{HEIGHT}p{FPS}",
        frameDuration=f"1/{FPS}s",
        width=str(WIDTH),
        height=str(HEIGHT),
    )
    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", name="Cronista")
    project = ET.SubElement(event, "project", name=project_name)
    attrs = {
        "format": FORMAT_ID,
        **sequence_attrs,
        "tcStart": "0s",
        "tcFormat": "NDF",
        "audioLayout": "stereo",
        "audioRate": "48k",
    }
    sequence = ET.SubElement(project, "sequence", attrs)
    return FcpxmlSkeleton(root, resources, sequence, ET.SubElement(sequence, "spine"))


def add_asset(resources: ET.Element, asset_id: str, name: str, src: str, frames: int, *, video: bool) -> None:
    """`asset` de vídeo (sem o áudio do master: o som vem dos WAVs ou stems) ou de áudio estéreo a 48 kHz."""
    attrs = {"id": asset_id, "name": name, "src": src, "start": "0s", "duration": fcpxml_time(frames)}
    if video:
        attrs |= {"format": FORMAT_ID, "hasVideo": "1", "hasAudio": "0"}
    else:
        attrs |= {"hasVideo": "0", "hasAudio": "1", "audioSources": "1", "audioChannels": "2"}
        attrs["audioRate"] = "48000"
    ET.SubElement(resources, "asset", attrs)


def serialize(root: ET.Element) -> str:
    ET.indent(root, space="  ")
    return XML_HEAD + ET.tostring(root, encoding="unicode") + "\n"
