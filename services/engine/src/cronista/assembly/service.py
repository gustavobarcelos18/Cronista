"""Liga o plano de montagem ao banco: capítulos, palavras da fala, B-roll e durações dos arquivos."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from cronista.assembly.plan import AssemblyParams, BrollClip, EditPlan, WordSpan, build_edit_plan
from cronista.audio.events import load_active_events
from cronista.config import Settings
from cronista.domain.frames import duration_frames
from cronista.montage import SessionPlanError, load_source
from cronista.story.service import (
    DEFAULT_TARGET_S,
    StoryResult,
    build_series_story,
    build_story,
    scope_sessions,
)


def build_assembly(
    db: Session,
    session_id: int | None,
    settings: Settings,
    target_s: float = DEFAULT_TARGET_S,
    profile_objectives: tuple[list[str], list[str]] = ([], []),
    params: AssemblyParams | None = None,
    project_id: int | None = None,
) -> EditPlan:
    return assemble(db, session_id, settings, target_s, profile_objectives, params, project_id)[0]


def assemble(
    db: Session,
    session_id: int | None,
    settings: Settings,
    target_s: float = DEFAULT_TARGET_S,
    profile_objectives: tuple[list[str], list[str]] = ([], []),
    params: AssemblyParams | None = None,
    project_id: int | None = None,
) -> tuple[EditPlan, StoryResult]:
    """Plano de montagem e a história de onde ele saiu (o acabamento lê os marcadores dos segmentos).

    Com `project_id`, é o vídeo da série: todas as sessões do projeto, com um alvo só.
    """
    overrides = settings.relevance_overrides
    sessions = scope_sessions(db, session_id, project_id)
    story = (
        build_series_story(db, project_id, target_s, profile_objectives, overrides)
        if project_id is not None
        else build_story(db, session_id or 0, target_s, profile_objectives, overrides)
    )
    words: dict[int, list[WordSpan]] = {}
    broll: dict[int, list[BrollClip]] = {}
    durations: dict[int, int] = {}
    for media in (m for s in sessions for m in sorted(s.media_files, key=lambda m: m.ordinal)):
        for event in load_active_events(db, media.id):
            ev = event.evidence
            if event.kind == "fala":
                for w in event.payload.get("words", []):
                    words.setdefault(media.id, []).append(
                        WordSpan(int(w["start_frame"]), int(w["end_frame"]))
                    )
            elif event.kind == "broll":
                tags = tuple(str(t) for t in event.payload.get("tags", []))
                broll.setdefault(media.id, []).append(
                    BrollClip(media.id, ev.start_frame, ev.end_frame, ev.confidence, tags)
                )
        try:
            duration_s = load_source(db, media).duration_s
        except SessionPlanError:
            duration_s = None
        if duration_s is not None:
            durations[media.id] = duration_frames(duration_s)
    plan = build_edit_plan(story.chapters, words=words, durations=durations, broll=broll, params=params)
    return plan, story


def write_plan(plan: EditPlan, directory: Path, session_id: int) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"plano-montagem-{session_id}.json"
    path.write_text(plan.to_json(), encoding="utf-8")
    return path
