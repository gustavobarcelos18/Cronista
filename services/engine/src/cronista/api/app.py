"""API HTTP local (FastAPI) que o Studio consome. 7A: só leitura de sessões, arquivos, jobs e marcadores."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select

from cronista.config import Settings
from cronista.db.models import Artifact, Job, Marker, MediaFile, RecordingSession
from cronista.db.session import open_db
from cronista.domain.models import StageResult
from cronista.relevance.service import load_segments


class MediaFileOut(BaseModel):
    id: int
    name: str
    ordinal: int
    size_bytes: int


class SessionOut(BaseModel):
    id: int
    project: str
    folder: str
    files: list[MediaFileOut]


class JobOut(BaseModel):
    id: int
    media_file_id: int
    stage: str
    variant: str
    status: str
    attempts: int
    error: str | None


class MarkerOut(BaseModel):
    id: int
    marker_id: str
    kind: str
    media_file_id: int | None
    media_frame: int
    source: str
    warning: str | None


class SegmentOut(BaseModel):
    start_s: int
    end_s: int
    classe: str
    score: float
    razoes: list[str]
    markers: list[str]
    features: dict[str, float]


def create_app(settings: Settings, origins: list[str] | None = None) -> FastAPI:
    app = FastAPI(title="Cronista Engine", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.env}

    @app.get("/sessions", response_model=list[SessionOut])
    def list_sessions() -> list[SessionOut]:
        with open_db(settings.db_path) as db:
            rows = db.scalars(select(RecordingSession).order_by(RecordingSession.id)).all()
            return [_session_out(s) for s in rows]

    @app.get("/sessions/{session_id}", response_model=SessionOut)
    def get_session(session_id: int) -> SessionOut:
        with open_db(settings.db_path) as db:
            row = db.get(RecordingSession, session_id)
            if row is None:
                raise HTTPException(404, "sessão não encontrada")
            return _session_out(row)

    @app.get("/sessions/{session_id}/jobs", response_model=list[JobOut])
    def session_jobs(session_id: int) -> list[JobOut]:
        with open_db(settings.db_path) as db:
            rows = db.scalars(
                select(Job)
                .join(MediaFile, Job.media_file_id == MediaFile.id)
                .where(MediaFile.session_id == session_id)
                .order_by(Job.id)
            ).all()
            return [
                JobOut(
                    id=j.id,
                    media_file_id=j.media_file_id,
                    stage=j.stage,
                    variant=j.variant,
                    status=j.status,
                    attempts=j.attempts,
                    error=j.error,
                )
                for j in rows
            ]

    @app.get("/sessions/{session_id}/markers", response_model=list[MarkerOut])
    def session_markers(session_id: int) -> list[MarkerOut]:
        with open_db(settings.db_path) as db:
            rows = db.scalars(
                select(Marker).where(Marker.session_id == session_id).order_by(Marker.media_frame)
            ).all()
            return [
                MarkerOut(
                    id=m.id,
                    marker_id=m.marker_id,
                    kind=m.kind,
                    media_file_id=m.media_file_id,
                    media_frame=m.media_frame,
                    source=m.source,
                    warning=m.warning,
                )
                for m in rows
            ]

    @app.get("/media/{media_id}/segments", response_model=list[SegmentOut])
    def media_segments(media_id: int) -> list[SegmentOut]:
        with open_db(settings.db_path) as db:
            if db.get(MediaFile, media_id) is None:
                raise HTTPException(404, "arquivo não encontrado")
            return [
                SegmentOut(
                    start_s=g.start_s,
                    end_s=g.end_s,
                    classe=g.classe,
                    score=g.score,
                    razoes=g.razoes,
                    markers=g.markers,
                    features=g.features,
                )
                for g in load_segments(db, media_id)
            ]

    @app.get("/media/{media_id}/video")
    def media_video(media_id: int) -> FileResponse:
        """Master normalizado (H.264 MP4); o FileResponse atende `Range`, então o player pode buscar."""
        with open_db(settings.db_path) as db:
            artifact = db.scalar(
                select(Artifact).where(
                    Artifact.media_file_id == media_id,
                    Artifact.stage == "normalize",
                    Artifact.variant == "",
                )
            )
            if artifact is None or not Path(artifact.result_path).is_file():
                raise HTTPException(404, "arquivo ainda não ingerido")
            result = StageResult.model_validate_json(Path(artifact.result_path).read_text(encoding="utf-8"))
        master = Path(str(result.data["media"]))
        if not master.is_file():
            raise HTTPException(404, "master não existe mais; rode `cronista ingest`")
        return FileResponse(master, media_type="video/mp4")

    return app


def _session_out(s: RecordingSession) -> SessionOut:
    return SessionOut(
        id=s.id,
        project=s.project.name,
        folder=s.folder,
        files=[
            MediaFileOut(id=f.id, name=Path(f.path).name, ordinal=f.ordinal, size_bytes=f.size_bytes)
            for f in s.media_files
        ],
    )
