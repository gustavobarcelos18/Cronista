"""Exportação da montagem (Fase 6C): FCPXML 1.9 multi-trilha, SRT em tempo de timeline e marcadores em Lua.

O FCPXML segue o desenho que o Resolve 21.2 importou no spike (histórico §39): `library > event > project`,
V1 no `spine`, tudo o mais como clipes conectados (`lane`) ao clipe de V1 que está embaixo. Mapa de lanes:

| lane | trilha | conteúdo |
|---|---|---|
| spine | V1 | gameplay e timelapses |
| 1 | V2 | zoom e tremor do acabamento (8D; vazia sem acabamento) |
| 2 | V3 | B-roll |
| 3 | V4 | contador de mortes do acabamento (8D) |
| 4 | V5 | cartela de capítulo, título editável |
| -1 / -2 | A1 / A2 | stems de jogo e de voz |
| -4 / -5 | A4 / A5 | música (stem ou arquivo) e SFX do acabamento (8D); A3 vazia |
| -6 / -7 | A6 / A7 | stems crus, desativados |

⚠️ O que o spike ainda não provou (plano 6.5, itens A16 e bloco D): se o Resolve respeita esses números de lane
sem trilhas intermediárias e se o canal desativado vale para A6/A7. Marcadores e trilhas vazias, se faltarem,
vêm do Lua colado no Console, pois o FCPXML não carrega marcador (spike).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from fractions import Fraction
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from cronista.assembly.plan import Card, EditPlan, Mode
from cronista.domain.frames import FPS, fcpxml_time
from cronista.domain.tracks import Track
from cronista.export.fcpxml import _parse_time, check_fcpxml
from cronista.export.fcpxml_base import add_asset, new_skeleton, serialize
from cronista.export.finish_fcpxml import FinishLayers, add_finish_clips
from cronista.mix.envelope import narration_cues
from cronista.story.models import ScriptLine

TITLE_UID = ".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti"
LANE_B_ROLL, LANE_CARD = Track.V3.lane, Track.V5.lane
STEM_LANES = {t.value: t.lane for t in (Track.A1, Track.A2, Track.A4, Track.A6, Track.A7)}
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


def render_plan_fcpxml(
    plan: EditPlan, media: ExportMedia, name: str = "Cronista", layers: FinishLayers | None = None
) -> str:
    skeleton = new_skeleton(name, duration=fcpxml_time(plan.total_frames))
    root, resources, spine = skeleton.root, skeleton.resources, skeleton.spine
    ids: dict[str, str] = {}

    def asset(path: Path, frames: int, *, video: bool) -> str:
        key = f"{'v' if video else 'a'}:{path}"
        if key not in ids:
            ids[key] = f"r{len(ids) + 3}"  # r1 = format, r2 = título
            add_asset(resources, ids[key], path.name, path.resolve().as_uri(), frames, video=video)
        return ids[key]

    ET.SubElement(resources, "effect", id="r2", name="Basic Title", uid=TITLE_UID)

    v1 = [(n, i) for n, i in enumerate(plan.items) if i.track == Track.V1]
    broll = [i for i in plan.items if i.track == Track.V3]
    cards = {c.timeline_start: c for c in plan.cards}
    title_count = 0
    fx_titles = [0]
    # Sem a duração do master, o asset vai até o maior corte do arquivo (não só o do primeiro).
    last_out: dict[int, int] = {}
    for i in plan.items:
        last_out[i.file_id] = max(last_out.get(i.file_id, 0), i.out_frame)
    for n, item in v1:
        if item.mode == Mode.TIMELAPSE:
            ref, start = asset(media.timelapses[n], item.timeline_frames, video=True), 0
        else:
            info = media.masters[item.file_id]
            ref, start = (
                asset(info.path, info.duration_frames or last_out[item.file_id], video=True),
                item.in_frame,
            )
        parent = ET.SubElement(
            spine,
            "asset-clip",
            ref=ref,
            name=f"{item.mode.value}|{item.segment_id}",
            offset=fcpxml_time(item.timeline_start),
            start=fcpxml_time(start),
            duration=fcpxml_time(item.timeline_frames),
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
                offset=fcpxml_time(start),
                start=fcpxml_time(item.timeline_start),
                duration=fcpxml_time(item.timeline_frames),
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
                ref=asset(info.path, info.duration_frames or last_out[b.file_id], video=True),
                lane=str(LANE_B_ROLL),
                name=f"B-roll|{b.segment_id}",
                offset=fcpxml_time(start),
                start=fcpxml_time(b.in_frame),
                duration=fcpxml_time(b.timeline_frames),
                format="r1",
            )
        if layers is not None:
            add_finish_clips(parent, item, start, layers, lambda p, f, v: asset(p, f, video=v), fx_titles)
        card = cards.get(item.timeline_start)
        if card is not None:
            title_count += 1
            _add_title(parent, card, start, min(card.frames, item.timeline_frames), title_count)

    return serialize(root)


def _add_title(parent: ET.Element, card: Card, parent_start: int, frames: int, n: int) -> None:
    title = ET.SubElement(
        parent,
        "title",
        ref="r2",
        lane=str(LANE_CARD),
        name=card.text,
        offset=fcpxml_time(parent_start),
        start="0s",
        duration=fcpxml_time(frames),
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
    out: list[tuple[TimelineMarker, int, int]] = []  # (marcador, 1º quadro do corte, quadro depois do fim)
    skipped: list[str] = []
    v1 = [i for i in plan.items if i.track == Track.V1 and i.mode != Mode.TIMELAPSE]
    for m in sorted(markers, key=lambda x: (x.file_id, x.frame)):
        host = next((i for i in v1 if i.file_id == m.file_id and i.in_frame <= m.frame < i.out_frame), None)
        if host is None:
            skipped.append(f"{m.kind}|{m.marker_id}: fora dos trechos da montagem")
            continue
        start = host.timeline_start
        marker = TimelineMarker(
            frame=start + m.frame - host.in_frame,
            color=MARKER_COLORS.get(m.kind, "Blue"),
            name=MARKER_NAMES.get(m.kind, m.kind),
            note=f"{m.kind}|{m.marker_id}; {host.beat}: {host.reason}",
            custom=f"{m.kind}|{m.marker_id}",
        )
        out.append((marker, start, start + host.out_frame - host.in_frame))
    out.sort(key=lambda entry: entry[0].frame)
    # Dois marcadores no mesmo quadro: o `AddMarker` do Resolve recusa o segundo (de memória, a verificar em
    # `prod`), então cada um ganha o quadro livre mais próximo **dentro do próprio corte**: para a frente e,
    # se o corte acabar, para trás. Sem quadro livre no corte, vira aviso (nunca cai no corte vizinho).
    taken: set[int] = set()
    shifted: list[TimelineMarker] = []
    for t, low, high in out:
        frame = next((f for f in _nearby_frames(t.frame, low, high) if f not in taken), None)
        if frame is None:
            skipped.append(f"{t.custom}: sem quadro livre no corte")
            continue
        taken.add(frame)
        shifted.append(replace(t, frame=frame) if frame != t.frame else t)
    return shifted, skipped


def _nearby_frames(frame: int, low: int, high: int) -> Iterator[int]:
    """`frame`, depois os seguintes até `high - 1`, depois os anteriores até `low`."""
    yield from range(frame, high)
    yield from range(frame - 1, low - 1, -1)


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
        {a.get("id", ""): a for a in resources.findall("asset")} if resources is not None else {}
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
