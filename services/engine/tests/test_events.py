"""Evidência e eventos (lacuna 2): validação, gravação, substituição por execução e filtros."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cronista.audio.events import load_events, load_stored_events, replace_events
from cronista.db.models import Event, MediaFile, Project, RecordingSession
from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource, params_hash


def make_event(kind: str, start: int, end: int, *, quote: str | None = None) -> AnalysisEvent:
    return AnalysisEvent(
        kind=kind,
        evidence=Evidence(
            source=EvidenceSource.TRANSCRICAO if quote else EvidenceSource.EVENTO,
            start_frame=start,
            end_frame=end,
            confidence=0.9,
            model="fake",
            model_version="1",
            params_hash=params_hash({"a": 1}),
            quote=quote,
        ),
        payload={"n": start},
    )


@pytest.fixture
def media_id(db: Session) -> int:
    project = Project(name="p")
    db.add(project)
    db.flush()
    session = RecordingSession(project_id=project.id, folder="x")
    db.add(session)
    db.flush()
    media = MediaFile(session_id=session.id, path="a.mp4")
    db.add(media)
    db.commit()
    return media.id


def _evidence(**over: Any) -> Evidence:
    fields: dict[str, Any] = {
        "source": EvidenceSource.SINAL,
        "model": "m",
        "model_version": "1",
        "params_hash": "h",
        "start_frame": 10,
        "end_frame": 20,
        "confidence": 0.5,
    }
    return Evidence(**{**fields, **over})


def test_evidence_rejects_inverted_interval_and_bad_numbers() -> None:
    with pytest.raises(ValidationError, match="invertido"):
        _evidence(start_frame=10, end_frame=5)
    with pytest.raises(ValidationError):
        _evidence(confidence=1.5)
    with pytest.raises(ValidationError):
        _evidence(start_frame=-1)
    assert _evidence(start_frame=7, end_frame=7).end_frame == 7  # evento pontual


def test_params_hash_is_stable_regardless_of_key_order() -> None:
    assert params_hash({"a": 1, "b": 2}) == params_hash({"b": 2, "a": 1})
    assert params_hash({"a": 1}) != params_hash({"a": 2})


def test_roundtrip_keeps_evidence_and_payload(db: Session, media_id: int) -> None:
    replace_events(db, media_id, "speech", "turbo", [make_event("fala", 60, 300, quote="oi gente")])
    (loaded,) = load_events(db, media_id)
    assert loaded.kind == "fala" and loaded.evidence.quote == "oi gente"
    assert loaded.evidence.source is EvidenceSource.TRANSCRICAO
    assert (loaded.evidence.start_frame, loaded.evidence.end_frame) == (60, 300)
    assert loaded.payload == {"n": 60}


def test_rerun_replaces_only_its_own_execution(db: Session, media_id: int) -> None:
    replace_events(db, media_id, "speech", "turbo", [make_event("fala", 0, 60), make_event("fala", 120, 180)])
    replace_events(db, media_id, "speech", "small", [make_event("fala", 0, 60)])
    replace_events(db, media_id, "sound_events", "", [make_event("risada", 30, 90)])

    replace_events(db, media_id, "speech", "turbo", [make_event("fala", 600, 660)])  # reexecução

    assert len(load_events(db, media_id, stage="speech", variant="turbo")) == 1
    assert len(load_events(db, media_id, stage="speech", variant="small")) == 1
    assert len(load_events(db, media_id, stage="sound_events")) == 1
    assert db.scalar(select(func.count()).select_from(Event)) == 3


def test_filters_by_kind_and_overlapping_window(db: Session, media_id: int) -> None:
    events = [make_event("fala", 0, 100), make_event("risada", 150, 200), make_event("fala", 300, 400)]
    replace_events(db, media_id, "s", "", events)
    assert [e.kind for e in load_events(db, media_id, kind="risada")] == ["risada"]
    window = load_events(db, media_id, start_frame=90, end_frame=160)
    assert [e.evidence.start_frame for e in window] == [0, 150]  # sobreposição, não só contidos
    assert load_events(db, media_id, start_frame=200, end_frame=300) == []  # bordas exclusivas
    assert [e.evidence.start_frame for e in load_events(db, media_id)] == [0, 150, 300]


def test_point_event_at_the_window_start_is_included_but_not_at_its_end(db: Session, media_id: int) -> None:
    replace_events(
        db, media_id, "s", "", [make_event("momento", 600, 600), make_event("momento", 1200, 1200)]
    )
    inside = load_events(db, media_id, start_frame=600, end_frame=1200)
    assert [e.evidence.start_frame for e in inside] == [600]  # janela [600, 1200): inclui 600, exclui 1200
    assert [e.evidence.start_frame for e in load_events(db, media_id, start_frame=601, end_frame=1300)] == [
        1200
    ]
    assert load_events(db, media_id, start_frame=0, end_frame=600) == []


def test_stored_events_say_which_execution_produced_them(db: Session, media_id: int) -> None:
    replace_events(db, media_id, "speech", "turbo", [make_event("fala", 0, 60)])
    replace_events(db, media_id, "sound_events", "", [make_event("risada", 30, 90)])
    stored = load_stored_events(db, media_id)
    assert [(s.producer, s.event.kind) for s in stored] == [
        ("speech:turbo", "fala"),
        ("sound_events", "risada"),
    ]
