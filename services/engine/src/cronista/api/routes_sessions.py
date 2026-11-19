"""Sessões, jobs, marcadores e roteiro."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from cronista.api.context import ApiContext
from cronista.api.schemas import (
    JobOut,
    MarkerOut,
    MediaFileOut,
    ScriptOut,
    SessionOut,
)
from cronista.db.models import Job, Marker, MediaFile, RecordingSession
from cronista.paths import SessionPaths
from cronista.story.models import Script
from cronista.story.script import load_script
from cronista.story.service import ScriptSaveError, save_script


def sessions_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()

    @router.get("/sessions", response_model=list[SessionOut])
    def list_sessions() -> list[SessionOut]:
        with ctx.connect() as db:
            rows = db.scalars(select(RecordingSession).order_by(RecordingSession.id)).all()
            return [_session_out(s) for s in rows]

    @router.get("/sessions/{session_id}", response_model=SessionOut)
    def get_session(session_id: int) -> SessionOut:
        with ctx.connect() as db:
            return _session_out(ctx.require_session(db, session_id))

    @router.get("/sessions/{session_id}/jobs", response_model=list[JobOut])
    def session_jobs(session_id: int) -> list[JobOut]:
        with ctx.connect() as db:
            ctx.require_session(db, session_id)
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

    @router.get("/sessions/{session_id}/markers", response_model=list[MarkerOut])
    def session_markers(session_id: int) -> list[MarkerOut]:
        with ctx.connect() as db:
            ctx.require_session(db, session_id)
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

    @router.get("/sessions/{session_id}/script", response_model=ScriptOut)
    def get_script(session_id: int) -> ScriptOut:
        with ctx.connect() as db:
            ctx.require_session(db, session_id)
        path = SessionPaths.of(ctx.settings, session_id).script
        if not path.is_file():
            raise HTTPException(404, "roteiro ainda não importado (`cronista roteiro-import`)")
        return ScriptOut(script=load_script(path))

    @router.put("/sessions/{session_id}/script", response_model=ScriptOut)
    def put_script(session_id: int, script: Script) -> ScriptOut:
        """Valida e grava o roteiro editado; a versão anterior vira `roteiro.v<N>.json`."""
        with ctx.connect() as db:
            ctx.require_session(db, session_id)
        try:
            report = save_script(SessionPaths.of(ctx.settings, session_id).story_dir, script)
        except ScriptSaveError as e:
            raise HTTPException(422, {"message": str(e), "errors": e.errors}) from e
        return ScriptOut(script=script.model_copy(update={"lines": report.lines}), warnings=report.warnings)

    return router


def _session_out(s: RecordingSession) -> SessionOut:
    return SessionOut(
        id=s.id,
        project_id=s.project_id,
        project=s.project.name,
        folder=s.folder,
        files=[
            MediaFileOut(id=f.id, name=Path(f.path).name, ordinal=f.ordinal, size_bytes=f.size_bytes)
            for f in s.media_files
        ],
    )
