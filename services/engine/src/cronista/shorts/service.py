"""Liga os candidatos a Shorts ao banco: segmentos, marcadores, emoção e fala de cada arquivo da sessão."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.assembly.plan import WordSpan
from cronista.audio.events import load_active_events
from cronista.config import Settings
from cronista.db.models import Marker, RecordingSession
from cronista.finishing.loader import load_style
from cronista.montage import SessionPlanError, load_masters
from cronista.paths import shorts_manifest_in
from cronista.pipeline.gpu import GpuGate
from cronista.relevance.engine import EMOTION
from cronista.review.decisions import load_effective_segments
from cronista.shorts.candidates import (
    Emotion,
    FileMaterial,
    ShortCandidate,
    ShortsParams,
    SpeechUtterance,
    pick_candidates,
    to_json,
)
from cronista.shorts.render import CaptionWord, ShortStyle, render_shorts


class ShortsError(Exception):
    """Sessão inexistente, sem segmentos ou sem material para os Shorts."""


def build_shorts(db: Session, session_id: int, params: ShortsParams | None = None) -> list[ShortCandidate]:
    session = db.get(RecordingSession, session_id)
    if session is None:
        raise ShortsError(f"sessão {session_id} não existe (veja `cronista status`)")
    materials: list[FileMaterial] = []
    for media in sorted(session.media_files, key=lambda m: m.ordinal):
        segments = load_effective_segments(db, media.id)
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
        raise ShortsError("sem segmentos; rode `cronista relevance` antes")
    return pick_candidates(materials, params)


def write_shorts(
    candidates: list[ShortCandidate],
    directory: Path,
    session_id: int,
    clips: Mapping[str, Path] | None = None,
) -> Path:
    """Manifesto da sessão: só o `shorts-render` o grava (com o clipe de cada candidato)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = shorts_manifest_in(directory, session_id)
    named = {key: clip.name for key, clip in clips.items()} if clips is not None else None
    path.write_text(to_json(candidates, named), encoding="utf-8")
    return path


def load_caption_words(db: Session, session_id: int) -> dict[int, list[CaptionWord]]:
    """Palavras do Whisper (com texto) de cada arquivo da sessão, para a legenda gravada."""
    session = db.get(RecordingSession, session_id)
    if session is None:
        raise ShortsError(f"sessão {session_id} não existe (veja `cronista status`)")
    out: dict[int, list[CaptionWord]] = {}
    for media in session.media_files:
        words = [
            CaptionWord(int(w["start_frame"]), int(w["end_frame"]), str(w.get("text", "")))
            for e in load_active_events(db, media.id)
            if e.kind == "fala"
            for w in e.payload.get("words", [])
        ]
        out[media.id] = sorted(words, key=lambda w: w.start_frame)
    return out


@dataclass
class ShortsPackage:
    candidates: list[ShortCandidate]
    clips: dict[str, Path]
    warnings: list[str] = field(default_factory=list)


def render_session_shorts(
    db: Session,
    session_id: int,
    settings: Settings,
    directory: Path,
    *,
    params: ShortsParams | None = None,
    style: ShortStyle | None = None,
    serie: str = "",
    gate: GpuGate | None = None,
) -> ShortsPackage:
    """Escolhe os candidatos e renderiza cada um em 9:16 com a identidade do brand kit (Fase 9A)."""
    from cronista.finishing.brand import brand_dir

    candidates = build_shorts(db, session_id, params)
    resolved, _ = load_style(settings, serie)
    session = db.get(RecordingSession, session_id)
    assert session is not None  # build_shorts já validou
    try:
        masters, notes = load_masters(db, session)
    except SessionPlanError as exc:
        raise ShortsError(str(exc)) from exc
    base_style = replace(style or ShortStyle(), loudness_lufs=resolved.brand.sonic.loudness_lufs)
    result = render_shorts(
        candidates,
        load_caption_words(db, session_id),
        masters,
        resolved.brand.visual,
        directory,
        settings,
        style=base_style,
        brand_dir=brand_dir(settings.brand_dir),
        gate=gate,
    )
    write_shorts(candidates, directory, session_id, result.clips)
    return ShortsPackage(candidates, result.clips, [*notes, *result.warnings])
