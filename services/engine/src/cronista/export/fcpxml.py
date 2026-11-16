"""FCPXML pelo caminho OTIO → adaptador `fcpx_xml`, com correções mínimas e validação estrutural.

Spike do adaptador (plano, seção 6.5; medido na 1B, histórico §30). O que ele faz bem: tempos em quadros
inteiros de 1/60 s, um clipe por trecho, áudio em lanes -1 (A1) e -2 (A2), um `asset` por arquivo.
O que corrigimos aqui, sem mudar a timeline: remover os `asset-clip` soltos na raiz (nada os referencia e a
posição não é válida no esquema ⚠️ de memória), dar largura/altura ao `format` e tirar o `uid` vazio.
Não existe DTD oficial offline: `check_fcpxml` confere o que dá para provar (referências, grade de quadros,
duração da sequência, lanes). A validação de verdade é a importação no Resolve (1C).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from fractions import Fraction

import opentimelineio as otio

from cronista.export.timeline import FPS

WIDTH, HEIGHT = 1920, 1080
_TIME_ATTRS = ("offset", "duration", "start")
_XML_HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n\n'


def render_fcpxml(timeline: otio.schema.Timeline) -> str:
    raw = otio.adapters.write_to_string(timeline, "fcpx_xml")
    root = ET.fromstring(raw)

    for element in list(root.findall("asset-clip")):  # soltos na raiz; os da sequência são <clip>
        root.remove(element)
    for fmt in root.iter("format"):
        fmt.set("name", f"FFVideoFormat{HEIGHT}p{FPS}")
        fmt.set("width", str(WIDTH))
        fmt.set("height", str(HEIGHT))
    for project in root.iter("project"):
        if project.get("uid") == "":
            del project.attrib["uid"]
    # O Resolve recusa `<project>` solto na raiz (erro "inherited value for key 'library'", 2026-11-16):
    # o esquema exige <library><event><project>, como nos arquivos do kit que importam.
    loose = root.find("project")
    if loose is not None:
        root.remove(loose)
        library = ET.SubElement(root, "library")
        event = ET.SubElement(library, "event", {"name": "Cronista"})
        event.append(loose)

    ET.indent(root, space="  ")
    return _XML_HEAD + ET.tostring(root, encoding="unicode") + "\n"


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

    ids = {e.get("id") for e in resources if e.get("id")}
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
        lanes = {c.get("lane") for c in spine.iter("clip")}
        if not {"-1", "-2"} <= lanes:
            problems.append("faltam as lanes de áudio -1 (A1, jogo) e -2 (A2, microfone)")
    return problems
