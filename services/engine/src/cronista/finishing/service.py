"""Liga o plano de acabamento ao resto do app: montagem (Fase 6), brand kit e biblioteca pessoal (8A)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from cronista.assembly.plan import LIVE_MODES, EditItem, EditPlan
from cronista.assembly.service import assemble
from cronista.config import Settings
from cronista.db.models import (
    Artifact,
    Event,
    Marker,
    NarrativeEvent,
    RecordingSession,
    SegmentDecision,
)
from cronista.domain.tracks import Track
from cronista.finishing.brand import ResolvedStyle
from cronista.finishing.library import Library
from cronista.finishing.plan import (
    AssetRef,
    CardRef,
    FinishPlan,
    Moment,
    build_finish_plan,
)
from cronista.story.arc import Chapter
from cronista.story.service import DEFAULT_TARGET_S, StoryResult, scope_sessions


def marker_kinds_by_segment(chapters: Sequence[Chapter]) -> dict[str, frozenset[str]]:
    """Tipos de marcador do criador (`morte_falha`, `engracado`...) por segmento da história."""
    return {
        item.span.segment_id: frozenset(item.marker_kinds) for chapter in chapters for item in chapter.items
    }


PEAK_PRIORITY = ("morte_falha", "conquista", "engracado", "momento")
"""Qual marcador do criador manda no pico do corte quando há mais de um (o resto cai no primeiro)."""

MarkerFrames = Mapping[int, Sequence[tuple[int, str]]]
"""`file_id` → `(quadro no arquivo, tipo)` de cada marcador do criador."""


def marker_peaks(db: Session, session_ids: int | Sequence[int]) -> dict[int, list[tuple[int, str]]]:
    """Marcadores do criador por arquivo: o pico do zoom é onde ele apertou a tecla."""
    ids = [session_ids] if isinstance(session_ids, int) else list(session_ids)
    out: dict[int, list[tuple[int, str]]] = {}
    for marker in db.scalars(select(Marker).where(Marker.session_id.in_(ids))):
        if marker.media_file_id is not None:
            out.setdefault(marker.media_file_id, []).append((marker.media_frame, marker.kind))
    return out


def _peak_in_timeline(item: EditItem, marks: Sequence[tuple[int, str]]) -> int | None:
    inside = [(f, k) for f, k in marks if item.in_frame <= f < item.out_frame]
    if not inside:
        return None
    rank = {kind: n for n, kind in enumerate(PEAK_PRIORITY)}
    frame = min(inside, key=lambda m: (rank.get(m[1], len(rank)), m[0]))[0]
    return item.timeline_start + (frame - item.in_frame) // max(item.speed, 1)


def moments_from_plan(
    plan: EditPlan, kinds: Mapping[str, frozenset[str]], peaks: MarkerFrames | None = None
) -> list[Moment]:
    """Um momento por corte de V1, em tempo de timeline. O pico é o marcador do criador no corte; sem ele,
    o pico é o meio do corte."""
    return [
        Moment(
            id=f"{item.file_id}:{item.segment_id}:{item.timeline_start}",
            chapter=item.chapter,
            start=item.timeline_start,
            frames=item.timeline_frames,
            score=min(1.0, max(0.0, item.score)),
            beat=item.beat,
            live=item.mode in LIVE_MODES,
            tags=frozenset().union(*(kinds.get(sid, frozenset()) for sid in item.segment_ids)),
            peak=_peak_in_timeline(item, (peaks or {}).get(item.file_id, ())),
        )
        for item in plan.items
        if item.track == Track.V1
    ]


def assets_from_library(library: Library, *, commercial: bool = True) -> list[AssetRef]:
    """Itens da biblioteca; com `commercial`, só os que têm licença para vídeo monetizado."""
    return [
        AssetRef(i.id, i.kind, frozenset(i.tags), i.mood, i.bpm)
        for i in sorted(library.items, key=lambda i: i.id)
        if i.commercial_use or not commercial
    ]


def finish_from_edit_plan(
    plan: EditPlan,
    kinds: Mapping[str, frozenset[str]],
    style: ResolvedStyle,
    library: Library | None = None,
    peaks: MarkerFrames | None = None,
) -> FinishPlan:
    return build_finish_plan(
        moments_from_plan(plan, kinds, peaks),
        style.effects,
        total_frames=plan.total_frames,
        max_total_per_minute=style.max_effects_per_minute,
        cards=[CardRef(c.chapter, c.timeline_start, c.frames) for c in plan.cards],
        assets=assets_from_library(library) if library is not None else [],
        preferred_music=style.brand.sonic.mood_themes,
        lut=style.brand.visual.lut,
    )


def build_finishing(
    db: Session,
    session_id: int | None,
    settings: Settings,
    style: ResolvedStyle,
    library: Library | None = None,
    target_s: float = DEFAULT_TARGET_S,
    profile_objectives: tuple[list[str], list[str]] = ([], []),
    assembled: tuple[EditPlan, StoryResult] | None = None,
    project_id: int | None = None,
) -> FinishPlan:
    """`assembled` reaproveita uma montagem já feita (a prévia do Studio guarda uma por sessão e alvo).

    Com `project_id`, é o acabamento do vídeo da série (todas as sessões do projeto).
    """
    plan, story = assembled or assemble(
        db, session_id, settings, target_s, profile_objectives, None, project_id
    )
    ids = [s.id for s in scope_sessions(db, session_id, project_id)]
    return finish_from_edit_plan(
        plan, marker_kinds_by_segment(story.chapters), style, library, marker_peaks(db, ids)
    )


def write_finish_plan(plan: FinishPlan, directory: Path, session_id: int | str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"acabamento-{session_id}.json"
    path.write_text(plan.to_json(), encoding="utf-8")
    return path


def assembly_fingerprint(db: Session, session_id: int, series: bool = False) -> tuple[int, ...]:
    """Muda sempre que algo que alimenta a montagem muda (eventos, artefatos, marcadores, decisões...).

    Essas tabelas só crescem ou são reescritas com ids novos, então o maior id e a contagem bastam. É a
    chave de cache da montagem na prévia do Studio, que senão refaria a história a cada clique.
    """
    session = db.get(RecordingSession, session_id)
    sessions = list(session.project.sessions) if session and series else [session] if session else []
    session_ids = [s.id for s in sessions]
    media_ids = [m.id for s in sessions for m in s.media_files]

    def stat(column: InstrumentedAttribute[int], condition: ColumnElement[bool]) -> tuple[int, int]:
        top, count = db.execute(select(func.max(column), func.count()).where(condition)).one()
        return int(top or 0), int(count)

    parts = (
        stat(Event.id, Event.media_file_id.in_(media_ids)),
        stat(Artifact.id, Artifact.media_file_id.in_(media_ids)),
        stat(Marker.id, Marker.session_id.in_(session_ids)),
        stat(SegmentDecision.id, SegmentDecision.media_file_id.in_(media_ids)),
        stat(NarrativeEvent.id, NarrativeEvent.session_id.in_(session_ids)),
    )
    return tuple(n for pair in parts for n in pair)
