"""Liga o plano de montagem ao banco: capítulos, palavras da fala, B-roll e durações dos arquivos."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from cronista.assembly.plan import AssemblyParams, BrollClip, EditPlan, WordSpan, build_edit_plan
from cronista.audio.events import load_active_events
from cronista.config import Settings
from cronista.db.models import RecordingSession
from cronista.montage import SessionPlanError, _load_source
from cronista.story.service import DEFAULT_TARGET_S, build_story


def build_assembly(
    db: Session,
    session_id: int,
    settings: Settings,
    target_s: float = DEFAULT_TARGET_S,
    profile_objectives: tuple[list[str], list[str]] = ([], []),
    params: AssemblyParams | None = None,
) -> EditPlan:
    story = build_story(db, session_id, target_s, profile_objectives)
    session = db.get(RecordingSession, session_id)
    assert session is not None  # build_story já validou
    words: dict[int, list[WordSpan]] = {}
    broll: dict[int, list[BrollClip]] = {}
    durations: dict[int, int] = {}
    for media in session.media_files:
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
            duration_s = _load_source(db, media).duration_s
        except SessionPlanError:
            duration_s = None
        if duration_s is not None:
            durations[media.id] = round(duration_s * 60)
    return build_edit_plan(story.chapters, words=words, durations=durations, broll=broll, params=params)


def write_plan(plan: EditPlan, directory: Path, session_id: int) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"plano-montagem-{session_id}.json"
    path.write_text(plan.to_json(), encoding="utf-8")
    return path
