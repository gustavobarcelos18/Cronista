"""Progresso dos jobs da sessão (consulta e fluxo SSE)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from cronista.api.context import ApiContext
from cronista.api.schemas import (
    ProgressOut,
)
from cronista.db.models import Job, MediaFile

MAX_STREAM_S = 6 * 3600.0
"""Teto de um fluxo SSE: um job "running" órfão (processo morto) não prende a conexão para sempre."""


def progress_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()

    def _progress(session_id: int) -> ProgressOut:
        with ctx.connect() as db:
            rows = db.execute(
                select(Job.status, Job.stage)
                .join(MediaFile, Job.media_file_id == MediaFile.id)
                .where(MediaFile.session_id == session_id)
                .order_by(Job.id)
            ).all()
        count = {k: sum(1 for st, _ in rows if st == k) for k in ("pending", "running", "done", "failed")}
        current = next((stage for st, stage in rows if st == "running"), None)
        return ProgressOut(
            total=len(rows), **count, active=bool(count["pending"] or count["running"]), current=current
        )

    @router.get("/sessions/{session_id}/progress", response_model=ProgressOut)
    def progress(session_id: int) -> ProgressOut:
        return _progress(session_id)

    @router.get("/sessions/{session_id}/progress/stream")
    def progress_stream(
        request: Request, session_id: int, interval_s: float = Query(1.0, ge=0.05, le=10)
    ) -> StreamingResponse:
        """SSE: um evento `progress` a cada mudança; encerra quando não há mais job pendente ou rodando."""

        async def events() -> AsyncIterator[str]:
            last: str | None = None
            started = time.monotonic()
            while time.monotonic() - started < MAX_STREAM_S:
                if await request.is_disconnected():
                    return  # aba fechada: libera a conexão em vez de esperar o job acabar
                snap = await run_in_threadpool(_progress, session_id)
                data = snap.model_dump_json()
                if data != last:
                    last = data
                    yield f"event: progress\ndata: {data}\n\n"
                if not snap.active:
                    break
                await asyncio.sleep(interval_s)
            yield "event: end\ndata: {}\n\n"

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    return router
