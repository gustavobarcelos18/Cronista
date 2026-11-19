"""Estado compartilhado pelos routers: configuração, sessões de banco e os carregadores opcionais."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.orm import Session, sessionmaker

from cronista.config import Settings
from cronista.db.models import RecordingSession
from cronista.finishing.loader import StyleLoader
from cronista.review.reexport import ProfileLoader, ReexportJobs


@dataclass
class ApiContext:
    settings: Settings
    factory: sessionmaker[Session]
    jobs: ReexportJobs
    profile_loader: ProfileLoader | None = None
    finishing_loader: StyleLoader | None = None

    @contextmanager
    def connect(self) -> Iterator[Session]:
        with self.factory() as session:
            yield session

    @staticmethod
    def require_session(db: Session, session_id: int) -> None:
        if db.get(RecordingSession, session_id) is None:
            raise HTTPException(404, "sessão não encontrada")
