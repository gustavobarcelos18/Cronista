"""Liga os candidatos a Shorts ao banco: segmentos, marcadores, emoção e fala de cada arquivo da sessão."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.assembly.plan import WordSpan
from cronista.audio.events import load_active_events
from cronista.db.models import Marker, RecordingSession
from cronista.relevance.engine import EMOTION
from cronista.relevance.service import load_segments
from cronista.shorts.candidates import (
    Emotion,
    FileMaterial,
    ShortCandidate,
    ShortsParams,
    SpeechUtterance,
    pick_candidates,
    to_json,
)
from cronista.story.service import StoryError


def build_shorts(db: Session, session_id: int, params: ShortsParams | None = None) -> list[ShortCandidate]:
    session = db.get(RecordingSession, session_id)
    if session is None:
        raise StoryError(f"sessão {session_id} não existe (veja `cronista status`)")
    materials: list[FileMaterial] = []
    for media in sorted(session.media_files, key=lambda m: m.ordinal):
        segments = load_segments(db, media.id)
        if not segments:
            continue
        marks = {
            m.marker_id: m.media_frame
            for m in db.scalars(select(Marker).where(Marker.media_file_id == media.id))
        }
        emotions: list[Emotion] = []
        speech: list[SpeechUtterance] = []
        for e in load_active_events(db, media.id):
            ev = e.evidence
            if e.kind in EMOTION:
                emotions.append(Emotion(ev.start_frame, ev.end_frame, ev.confidence))
            elif e.kind == "fala":
                words = tuple(
                    WordSpan(int(w["start_frame"]), int(w["end_frame"])) for w in e.payload.get("words", [])
                )
                speech.append(SpeechUtterance(ev.start_frame, ev.end_frame, words))
        materials.append(FileMaterial(media.id, segments, marks, emotions, speech))
    if not materials:
        raise StoryError("sem segmentos; rode `cronista relevance` antes")
    return pick_candidates(materials, params)


def write_shorts(candidates: list[ShortCandidate], directory: Path, session_id: int) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"shorts-{session_id}.json"
    path.write_text(to_json(candidates), encoding="utf-8")
    return path
