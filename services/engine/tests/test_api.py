from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cronista.api.app import create_app
from cronista.config import Settings
from cronista.db.models import Artifact, Marker, MediaFile, Project, RecordingSession
from cronista.domain.models import StageResult


def _seed(db: Session) -> None:
    project = Project(name="serie")
    session = RecordingSession(project=project, folder="pasta")
    media = MediaFile(session=session, path="C:/x/a.mp4", ordinal=0, size_bytes=10)
    db.add_all([project, session, media])
    db.flush()
    db.add(
        Marker(session_id=session.id, media_file_id=media.id, marker_id="1", kind="novo_dia", media_frame=60)
    )
    db.commit()


def test_api_le_sessoes_e_marcadores(settings: Settings, db: Session) -> None:
    _seed(db)
    client = TestClient(create_app(settings))
    assert client.get("/health").json()["status"] == "ok"
    sessions = client.get("/sessions").json()
    assert sessions[0]["project"] == "serie" and sessions[0]["files"][0]["name"] == "a.mp4"
    assert client.get("/sessions/1/markers").json()[0]["media_frame"] == 60
    assert client.get("/sessions/1/jobs").json() == []
    assert client.get("/sessions/99").status_code == 404


def test_api_segmentos_e_video(settings: Settings, db: Session, tmp_path: Path) -> None:
    _seed(db)
    client = TestClient(create_app(settings))
    assert client.get("/media/1/segments").json() == []
    assert client.get("/media/99/segments").status_code == 404
    assert client.get("/media/1/video").status_code == 404

    video = tmp_path / "m.mp4"
    video.write_bytes(b"0123456789")
    result = tmp_path / "normalize.json"
    result.write_text(StageResult(data={"media": str(video)}).model_dump_json())
    db.add(Artifact(media_file_id=1, stage="normalize", cache_key="k", result_path=str(result)))
    db.commit()
    resp = client.get("/media/1/video", headers={"Range": "bytes=2-4"})
    assert resp.status_code == 206 and resp.content == b"234"


def test_api_eventos_e_waveform(settings: Settings, db: Session, tmp_path: Path) -> None:
    import numpy as np

    from cronista.audio.events import replace_events
    from cronista.audio.signals import SIGNALS_KEY, write_signal
    from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource

    _seed(db)
    client = TestClient(create_app(settings))
    assert client.get("/media/99/events").status_code == 404
    assert client.get("/media/1/waveform").status_code == 404  # sem sinais ainda

    ev = Evidence(
        source=EvidenceSource.EVENTO,
        start_frame=120,
        end_frame=180,
        confidence=0.8,
        model="m",
        model_version="1",
        params_hash="h",
    )
    replace_events(db, 1, "speech", "", [AnalysisEvent(kind="speech", evidence=ev)])
    replace_events(db, 1, "relevance", "", [AnalysisEvent(kind="segment", evidence=ev)])
    events = client.get("/media/1/events").json()
    assert [(e["stage"], e["start_s"], e["end_s"]) for e in events] == [("speech", 2.0, 3.0)]

    meta = write_signal(
        tmp_path,
        "game.energy_db",
        np.linspace(-60, 0, 100),
        unit="dBFS",
        source_track="game",
        version="1",
        params={},
    )
    result = tmp_path / "signals.json"
    result.write_text(
        StageResult(data={SIGNALS_KEY: {"game.energy_db": meta.model_dump()}}).model_dump_json()
    )
    db.add(Artifact(media_file_id=1, stage="audio_signals", cache_key="k2", result_path=str(result)))
    db.commit()
    wave = client.get("/media/1/waveform?points=10").json()
    assert len(wave["game"]) == 10 and wave["mic"] == [] and wave["duration_s"] == 10.0
    assert wave["game"][-1] == 0.0
