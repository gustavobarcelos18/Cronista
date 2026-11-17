from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cronista.api.app import create_app
from cronista.config import Settings
from cronista.db.models import Marker, MediaFile, Project, RecordingSession


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
