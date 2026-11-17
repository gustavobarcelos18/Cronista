"""Exportação da montagem (Fase 6C): FCPXML 1.9 multi-trilha, SRT em tempo de timeline e marcadores em Lua.

O FCPXML segue o desenho que o Resolve 21.2 importou no spike (histórico §39): `library > event > project`,
V1 no `spine`, tudo o mais como clipes conectados (`lane`) ao clipe de V1 que está embaixo. Mapa de lanes:

| lane | trilha | conteúdo |
|---|---|---|
| spine | V1 | gameplay e timelapses |
| 2 | V3 | B-roll (V2 fica vazia: o FCPXML não cria trilha vazia) |
| 4 | V5 | cartela de capítulo, título editável (V4 vazia) |
| -1 / -2 | A1 / A2 | stems de jogo e de voz |
| -6 / -7 | A6 / A7 | stems crus, desativados (A3 a A5 vazias) |

⚠️ O que o spike ainda não provou (plano 6.5, itens A16 e bloco D): se o Resolve respeita esses números de lane
sem trilhas intermediárias e se o canal desativado vale para A6/A7. Marcadores e trilhas vazias, se faltarem,
vêm do Lua colado no Console, pois o FCPXML não carrega marcador (spike).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from cronista.assembly.plan import Card, EditPlan, Mode, Track
from cronista.domain.frames import FPS
from cronista.export.fcpxml import _parse_time, check_fcpxml
from cronista.mix.envelope import narration_cues
from cronista.story.models import ScriptLine

WIDTH, HEIGHT = 1920, 1080
_XML_HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n\n'
TITLE_UID = ".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti"
LANE_B_ROLL, LANE_CARD = 2, 4
STEM_LANES = {"A1": -1, "A2": -2, "A6": -6, "A7": -7}
DISABLED_STEMS = frozenset({"A6", "A7"})


@dataclass(frozen=True)
class MediaFileInfo:
    path: Path
    duration_frames: int | None = None


@dataclass
class ExportMedia:
    """Referências do FCPXML: masters por arquivo, timelapses por índice do item, stems por nome (A1...)."""

    masters: Mapping[int, MediaFileInfo]
    timelapses: Mapping[int, Path] = field(default_factory=dict)
    stems: Mapping[str, Path] = field(default_factory=dict)
    stem_frames: int = 0


def _t(frames: int) -> str:
    return f"{frames}/{FPS}s"


def render_plan_fcpxml(plan: EditPlan, media: ExportMedia, name: str = "Cronista") -> str:
    root = ET.Element("fcpxml", version="1.9")
    resources = ET.SubElement(root, "resources")
    ET.SubElement(
        resources,
        "format",
        id="r1",
        name=f"FFVideoFormat{HEIGHT}p{FPS}",
        frameDuration=f"1/{FPS}s",
        width=str(WIDTH),
        height=str(HEIGHT),
    )
    ids: dict[str, str] = {}

    def asset(path: Path, frames: int, *, video: bool) -> str:
        key = f"{'v' if video else 'a'}:{path}"
        if key not in ids:
            ids[key] = f"r{len(ids) + 3}"  # r1 = format, r2 = título
            attrs = {
                "id": ids[key],
                "name": path.name,
                "src": path.resolve().as_uri(),
                "start": "0s",
                "duration": _t(frames),
            }
            if video:  # o áudio do master fica de fora: o som vem dos stems
                attrs |= {"format": "r1", "hasVideo": "1", "hasAudio": "0"}
            else:
                attrs |= {"hasVideo": "0", "hasAudio": "1", "audioSources": "1", "audioChannels": "2"}
                attrs["audioRate"] = "48000"
            ET.SubElement(resources, "asset", attrs)
        return ids[key]

    ET.SubElement(resources, "effect", id="r2", name="Basic Title", uid=TITLE_UID)

    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", name="Cronista")
    project = ET.SubElement(event, "project", name=name)
    sequence = ET.SubElement(
        project,
        "sequence",
        format="r1",
        duration=_t(plan.total_frames),
        tcStart="0s",
        tcFormat="NDF",
        audioLayout="stereo",
        audioRate="48k",
    )
    spine = ET.SubElement(sequence, "spine")

    v1 = [(n, i) for n, i in enumerate(plan.items) if i.track == Track.V1]
    broll = [i for i in plan.items if i.track == Track.V3]
    cards = {c.timeline_start: c for c in plan.cards}
    title_count = 0
    for n, item in v1:
        if item.mode == Mode.TIMELAPSE:
            ref, start = asset(media.timelapses[n], item.timeline_frames, video=True), 0
        else:
            info = media.masters[item.file_id]
            ref, start = asset(info.path, info.duration_frames or item.out_frame, video=True), item.in_frame
        parent = ET.SubElement(
            spine,
            "asset-clip",
            ref=ref,
            name=f"{item.mode.value}|{item.segment_id}",
            offset=_t(item.timeline_start),
            start=_t(start),
            duration=_t(item.timeline_frames),
            format="r1",
            tcFormat="NDF",
        )
        # O deslocamento de um clipe conectado conta no tempo do pai, que começa em `start`.
        for label, lane in STEM_LANES.items():
            stem = media.stems.get(label)
            if stem is None:
                continue
            child = ET.SubElement(
                parent,
                "asset-clip",
                ref=asset(stem, media.stem_frames, video=False),
                lane=str(lane),
                name=label,
                offset=_t(start),
                start=_t(item.timeline_start),
                duration=_t(item.timeline_frames),
            )
            if label in DISABLED_STEMS:
                ET.SubElement(child, "audio-channel-source", srcCh="1, 2", enabled="0")
        for b in broll:
            if b.timeline_start != item.timeline_start:
                continue
            info = media.masters[b.file_id]
            ET.SubElement(
                parent,
                "asset-clip",
                ref=asset(info.path, info.duration_frames or b.out_frame, video=True),
                lane=str(LANE_B_ROLL),
                name=f"B-roll|{b.segment_id}",
                offset=_t(start),
                start=_t(b.in_frame),
                duration=_t(b.timeline_frames),
                format="r1",
            )
        card = cards.get(item.timeline_start)
        if card is not None:
            title_count += 1
            _add_title(parent, card, start, min(card.frames, item.timeline_frames), title_count)

    ET.indent(root, space="  ")
    return _XML_HEAD + ET.tostring(root, encoding="unicode") + "\n"


def _add_title(parent: ET.Element, card: Card, parent_start: int, frames: int, n: int) -> None:
    title = ET.SubElement(
        parent,
        "title",
        ref="r2",
        lane=str(LANE_CARD),
        name=card.text,
        offset=_t(parent_start),
        start="0s",
        duration=_t(frames),
    )
    style = f"ts{n}"
    text = ET.SubElement(title, "text")
    ET.SubElement(text, "text-style", ref=style).text = card.text
    definition = ET.SubElement(title, "text-style-def", id=style)
    ET.SubElement(definition, "text-style", font="Helvetica", fontSize="120", fontColor="1 1 1 1")


# ------------------------------------------------------------------------------------------------- legenda


def _srt_time(frames: int) -> str:
    ms = round(frames * 1000 / FPS)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _cue_text(line: ScriptLine) -> str:
    return ("[ANTECIPAÇÃO] " if line.kind == "antecipacao" else "") + line.text


def render_timeline_srt(plan: EditPlan, lines: Sequence[ScriptLine]) -> str:
    """SRT do roteiro em tempo de timeline, com fala vazia em 0 s (evita o deslocamento de 1 s no Resolve)."""
    cues = [(0, FPS, ".")]
    cues += [(a, b, _cue_text(line)) for a, b, line in narration_cues(plan.items, lines)]
    return "\n".join(
        f"{n}\n{_srt_time(a)} --> {_srt_time(b)}\n{text}\n" for n, (a, b, text) in enumerate(cues, start=1)
    )


# ---------------------------------------------------------------------------------------------- marcadores

MARKER_COLORS = {
    "momento": "Blue",
    "morte_falha": "Red",
    "engracado": "Yellow",
    "conquista": "Green",
    "novo_dia": "Purple",
    "construcao": "Cyan",
    "foto_progresso": "Pink",
    "cinematica": "Fuchsia",
}
MARKER_NAMES = {
    "momento": "Momento",
    "morte_falha": "Morte/falha",
    "engracado": "Engraçado",
    "conquista": "Conquista",
    "novo_dia": "Novo dia",
    "construcao": "Construção",
    "foto_progresso": "Foto de progresso",
    "cinematica": "Cinemática",
}


@dataclass(frozen=True)
class MarkerInput:
    file_id: int
    frame: int
    kind: str
    marker_id: str


@dataclass(frozen=True)
class TimelineMarker:
    frame: int
    color: str
    name: str
    note: str
    custom: str


def timeline_markers(
    plan: EditPlan, markers: Sequence[MarkerInput]
) -> tuple[list[TimelineMarker], list[str]]:
    """Marcadores levados para a timeline; o que caiu fora dos trechos usados vira aviso, não erro."""
    out: list[TimelineMarker] = []
    skipped: list[str] = []
    v1 = [i for i in plan.items if i.track == Track.V1 and i.mode != Mode.TIMELAPSE]
    for m in sorted(markers, key=lambda x: (x.file_id, x.frame)):
        host = next((i for i in v1 if i.file_id == m.file_id and i.in_frame <= m.frame < i.out_frame), None)
        if host is None:
            skipped.append(f"{m.kind}|{m.marker_id}: fora dos trechos da montagem")
            continue
        out.append(
            TimelineMarker(
                frame=host.timeline_start + m.frame - host.in_frame,
                color=MARKER_COLORS.get(m.kind, "Blue"),
                name=MARKER_NAMES.get(m.kind, m.kind),
                note=f"{m.kind}|{m.marker_id}; {host.beat}: {host.reason}",
                custom=f"{m.kind}|{m.marker_id}",
            )
        )
    return sorted(out, key=lambda t: t.frame), skipped


def _lua_string(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")
    return f'"{escaped}"'


LUA_HEAD = (
    "local t = resolve:GetProjectManager():GetCurrentProject():GetCurrentTimeline(); local n = 0; "
    "local function m(f, c, a, b, d) if t:AddMarker(f, c, a, b, 1, d) then n = n + 1 end end;"
)
LUA_TAIL = ' print("marcadores adicionados: " .. n)'


def marker_lua(markers: Sequence[TimelineMarker], max_chars: int = 6000) -> list[str]:
    """Lua de **uma linha** para colar no Console do Resolve (sem `io`, `dofile` nem `require`).

    Cada linha é independente: passando de `max_chars` a lista é partida em várias, para colar uma de cada vez
    (o limite real do Console é uma medida que falta no spike; 6000 é um palpite conservador).
    """
    chunks: list[str] = []
    current = LUA_HEAD
    for t in markers:
        call = (
            f"m({t.frame}, {_lua_string(t.color)}, {_lua_string(t.name)}, "
            f"{_lua_string(t.note)}, {_lua_string(t.custom)});"
        )
        if len(current) + len(call) + len(LUA_TAIL) > max_chars and current != LUA_HEAD:
            chunks.append(current + LUA_TAIL)
            current = LUA_HEAD
        current += " " + call
    if current != LUA_HEAD or not chunks:
        chunks.append(current + LUA_TAIL)
    return chunks


def check_plan_fcpxml(xml: str, plan: EditPlan) -> list[str]:
    """Estrutura (`check_fcpxml`) mais duração total, arquivos existentes e limites dos clipes."""
    problems = check_fcpxml(xml)
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return problems
    resources = root.find("resources")
    assets: dict[str, ET.Element] = (
        {a.get("id", ""): a for a in resources.findall("asset")} if resources else {}
    )
    for a in assets.values():
        parsed = urlparse(a.get("src", ""))
        if not Path(url2pathname(parsed.path)).is_file():
            problems.append(f"asset {a.get('name')}: arquivo não existe ({a.get('src')})")
    for clip in root.iter("asset-clip"):
        asset = assets.get(clip.get("ref", ""))
        if asset is None:
            continue
        total = _parse_time(asset.get("duration", ""))
        start = _parse_time(clip.get("start", "0s"))
        duration = _parse_time(clip.get("duration", "0s"))
        if total is not None and start is not None and duration is not None and start + duration > total:
            problems.append(f"clipe {clip.get('name')}: passa do fim do arquivo {asset.get('name')}")
    sequence = root.find("library/event/project/sequence")
    if sequence is not None and _parse_time(sequence.get("duration", "")) != Fraction(plan.total_frames, FPS):
        problems.append("duração da sequência difere da soma de V1 do plano")
    return problems
