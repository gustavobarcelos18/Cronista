"""Liga o plano de acabamento ao resto do app: montagem (Fase 6), brand kit e biblioteca pessoal (8A)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from cronista.assembly.plan import LIVE_MODES, EditPlan
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
from cronista.story.service import DEFAULT_TARGET_S, StoryResult


def marker_kinds_by_segment(chapters: Sequence[Chapter]) -> dict[str, frozenset[str]]:
    """Tipos de marcador do criador (`morte_falha`, `engracado`...) por segmento da história."""
    return {
        item.span.segment_id: frozenset(item.marker_kinds) for chapter in chapters for item in chapter.items
    }


def moments_from_plan(plan: EditPlan, kinds: Mapping[str, frozenset[str]]) -> list[Moment]:
    """Um momento por corte de V1, em tempo de timeline. Sem pico conhecido, o pico é o meio do corte."""
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
) -> FinishPlan:
    return build_finish_plan(
        moments_from_plan(plan, kinds),
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
    session_id: int,
    settings: Settings,
    style: ResolvedStyle,
    library: Library | None = None,
    target_s: float = DEFAULT_TARGET_S,
    profile_objectives: tuple[list[str], list[str]] = ([], []),
    assembled: tuple[EditPlan, StoryResult] | None = None,
) -> FinishPlan:
    """`assembled` reaproveita uma montagem já feita (a prévia do Studio guarda uma por sessão e alvo)."""
    plan, story = assembled or assemble(db, session_id, settings, target_s, profile_objectives)
    return finish_from_edit_plan(plan, marker_kinds_by_segment(story.chapters), style, library)


def write_finish_plan(plan: FinishPlan, directory: Path, session_id: int) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"acabamento-{session_id}.json"
    path.write_text(plan.to_json(), encoding="utf-8")
    return path


def assembly_fingerprint(db: Session, session_id: int) -> tuple[int, ...]:
    """Muda sempre que algo que alimenta a montagem muda (eventos, artefatos, marcadores, decisões...).

    Essas tabelas só crescem ou são reescritas com ids novos, então o maior id e a contagem bastam. É a
    chave de cache da montagem na prévia do Studio, que senão refaria a história a cada clique.
    """
    session = db.get(RecordingSession, session_id)
    media_ids = [m.id for m in session.media_files] if session else []

    def stat(column: InstrumentedAttribute[int], condition: ColumnElement[bool]) -> tuple[int, int]:
        top, count = db.execute(select(func.max(column), func.count()).where(condition)).one()
        return int(top or 0), int(count)

    parts = (
        stat(Event.id, Event.media_file_id.in_(media_ids)),
        stat(Artifact.id, Artifact.media_file_id.in_(media_ids)),
        stat(Marker.id, Marker.session_id == session_id),
        stat(SegmentDecision.id, SegmentDecision.media_file_id.in_(media_ids)),
        stat(NarrativeEvent.id, NarrativeEvent.session_id == session_id),
    )
    return tuple(n for pair in parts for n in pair)
