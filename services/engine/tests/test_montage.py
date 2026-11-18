"""Plano da sessão (B18): gravação sem ingestão vira aviso, como em `load_masters`."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from cronista.config import Settings
from cronista.db.models import Marker, MediaFile, Project, RecordingSession
from cronista.montage import SessionPlanError, SourceFile, plan_session


def _two_files(db: Session) -> int:
    project = Project(name="serie")
    session = RecordingSession(project=project, folder="pasta")
    first = MediaFile(session=session, path="C:/x/a.mp4", ordinal=0, size_bytes=10)
    second = MediaFile(session=session, path="C:/x/b.mp4", ordinal=1, size_bytes=10)
    db.add_all([project, session, first, second])
    db.flush()
    db.add_all(
        [
            Marker(
                session_id=session.id, media_file_id=first.id, marker_id="1", kind="momento", media_frame=1800
            ),
            Marker(
                session_id=session.id,
                media_file_id=second.id,
                marker_id="2",
                kind="momento",
                media_frame=1800,
            ),
        ]
    )
    db.commit()
    return session.id


def test_plano_ignora_gravacao_sem_ingestao_com_aviso(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = _two_files(db)

    def fake(_db: Session, media: MediaFile) -> SourceFile:
        if media.ordinal == 1:
            raise SessionPlanError(f"{Path(media.path).name} ainda não foi ingerido (rode `cronista ingest`)")
        return SourceFile(media.id, Path("a-master.mp4"), 120.0, None, None)

    monkeypatch.setattr("cronista.montage.load_source", fake)
    plan = plan_session(db, session_id, settings)
    assert {w.file_id for w in plan.windows} == {1}
    assert any("b.mp4" in w for w in plan.warnings)


def test_plano_falha_se_nenhuma_gravacao_foi_ingerida(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = _two_files(db)

    def fake(_db: Session, media: MediaFile) -> SourceFile:
        raise SessionPlanError("nada ingerido")

    monkeypatch.setattr("cronista.montage.load_source", fake)
    with pytest.raises(SessionPlanError, match="nada ingerido"):
        plan_session(db, session_id, settings)
