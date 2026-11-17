"""API HTTP local (FastAPI) que o Studio consome. 7A: só leitura de sessões, arquivos, jobs e marcadores."""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from cronista.audio.events import load_stored_events
from cronista.audio.signals import load_signal, signal_metas
from cronista.config import Settings
from cronista.db.models import Artifact, Job, Marker, MediaFile, RecordingSession
from cronista.db.session import open_db
from cronista.domain.frames import FPS
from cronista.domain.models import StageResult
from cronista.relevance.service import load_segments
from cronista.review.decisions import current_decisions, record_decision
from cronista.review.panel import SeriesPanelOut, series_panel_full
from cronista.review.reexport import ProfileLoader, ReexportJobs
from cronista.story.models import Script
from cronista.story.script import load_script
from cronista.story.service import ScriptSaveError, save_script


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
    decision: str | None = None
    adj_start_s: float | None = None
    adj_end_s: float | None = None


class ScriptOut(BaseModel):
    script: Script
    warnings: list[str] = []


class ExportStatusOut(BaseModel):
    state: Literal["idle", "running", "done", "error"]
    message: str = ""
    version: int | None = None
    reused: bool = False
    directory: str | None = None
    problems: list[str] = []
    warnings: list[str] = []


class ProgressOut(BaseModel):
    """Jobs da sessão por estado; `active` vale enquanto houver job pendente ou rodando."""

    total: int
    pending: int
    running: int
    done: int
    failed: int
    active: bool
    current: str | None = None


class DecisionIn(BaseModel):
    decision: Literal["aceito", "rejeitado", "ajustado"]
    start_s: float | None = None
    end_s: float | None = None


class EventOut(BaseModel):
    stage: str
    variant: str
    kind: str
    start_s: float
    end_s: float
    source: str
    confidence: float
    quote: str | None


class WaveformOut(BaseModel):
    """Envelope de energia (dBFS) por faixa, em até `points` buckets uniformes (máximo de cada bucket)."""

    duration_s: float
    points: int
    game: list[float]
    mic: list[float]


def _envelope(values: np.ndarray, points: int) -> list[float]:
    if len(values) == 0:
        return []
    buckets = np.array_split(np.asarray(values, dtype=np.float32), min(points, len(values)))
    return [round(float(b.max()), 1) for b in buckets]


def create_app(
    settings: Settings, origins: list[str] | None = None, profile_loader: ProfileLoader | None = None
) -> FastAPI:
    app = FastAPI(title="Cronista Engine", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["*"],
    )

    jobs = ReexportJobs(settings, profile_loader)
    app.state.reexport = jobs

    @app.get("/sessions/{session_id}/export", response_model=ExportStatusOut)
    def export_status(session_id: int) -> ExportStatusOut:
        return ExportStatusOut(**asdict(jobs.status(session_id)))

    @app.post("/sessions/{session_id}/export", response_model=ExportStatusOut, status_code=202)
    def start_export(session_id: int, target_min: float = Query(40.0, gt=0, le=240)) -> ExportStatusOut:
        """Re-exporta com as decisões e o roteiro atuais; o cache por hash reaproveita o que não mudou."""
        with open_db(settings.db_path) as db:
            if db.get(RecordingSession, session_id) is None:
                raise HTTPException(404, "sessão não encontrada")
        if not jobs.start(session_id, target_min * 60):
            raise HTTPException(409, "já há uma exportação em andamento")
        return ExportStatusOut(**asdict(jobs.status(session_id)))

    def _progress(session_id: int) -> ProgressOut:
        with open_db(settings.db_path) as db:
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

    @app.get("/sessions/{session_id}/progress", response_model=ProgressOut)
    def progress(session_id: int) -> ProgressOut:
        return _progress(session_id)

    @app.get("/sessions/{session_id}/progress/stream")
    def progress_stream(session_id: int, interval_s: float = Query(1.0, ge=0.05, le=10)) -> StreamingResponse:
        """SSE: um evento `progress` a cada mudança; encerra quando não há mais job pendente ou rodando."""

        def events() -> Iterator[str]:
            last: str | None = None
            while True:
                snap = _progress(session_id)
                data = snap.model_dump_json()
                if data != last:
                    last = data
                    yield f"event: progress\ndata: {data}\n\n"
                if not snap.active:
                    yield "event: end\ndata: {}\n\n"
                    return
                time.sleep(interval_s)

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    @app.get("/series", response_model=SeriesPanelOut)
    def series() -> SeriesPanelOut:
        with open_db(settings.db_path) as db:
            return series_panel_full(db)

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

    @app.get("/sessions/{session_id}/script", response_model=ScriptOut)
    def get_script(session_id: int) -> ScriptOut:
        path = settings.data_dir / "story" / str(session_id) / "roteiro.json"
        if not path.is_file():
            raise HTTPException(404, "roteiro ainda não importado (`cronista roteiro-import`)")
        return ScriptOut(script=load_script(path))

    @app.put("/sessions/{session_id}/script", response_model=ScriptOut)
    def put_script(session_id: int, script: Script) -> ScriptOut:
        """Valida e grava o roteiro editado; a versão anterior vira `roteiro.v<N>.json`."""
        try:
            report = save_script(settings.data_dir / "story" / str(session_id), script)
        except ScriptSaveError as e:
            raise HTTPException(422, {"message": str(e), "errors": e.errors}) from e
        return ScriptOut(script=script.model_copy(update={"lines": report.lines}), warnings=report.warnings)

    @app.get("/media/{media_id}/segments", response_model=list[SegmentOut])
    def media_segments(media_id: int) -> list[SegmentOut]:
        with open_db(settings.db_path) as db:
            if db.get(MediaFile, media_id) is None:
                raise HTTPException(404, "arquivo não encontrado")
            decisions = current_decisions(db, media_id)
            return [
                SegmentOut(
                    start_s=g.start_s,
                    end_s=g.end_s,
                    classe=g.classe,
                    score=g.score,
                    razoes=g.razoes,
                    markers=g.markers,
                    features=g.features,
                    decision=d.decision if (d := decisions.get(g.start_s)) else None,
                    adj_start_s=d.start_s if d else None,
                    adj_end_s=d.end_s if d else None,
                )
                for g in load_segments(db, media_id)
            ]

    @app.post("/media/{media_id}/segments/{seg_start_s}/decision", response_model=SegmentOut)
    def decide_segment(media_id: int, seg_start_s: int, body: DecisionIn) -> SegmentOut:
        """Aceita, rejeita ou ajusta os limites de um segmento. Só insere (histórico preservado)."""
        with open_db(settings.db_path) as db:
            if db.get(MediaFile, media_id) is None:
                raise HTTPException(404, "arquivo não encontrado")
            seg = next((g for g in load_segments(db, media_id) if g.start_s == seg_start_s), None)
            if seg is None:
                raise HTTPException(404, "segmento não encontrado")
            try:
                d = record_decision(db, media_id, seg_start_s, body.decision, body.start_s, body.end_s)
            except ValueError as e:
                raise HTTPException(422, str(e)) from e
            return SegmentOut(
                start_s=seg.start_s,
                end_s=seg.end_s,
                classe=seg.classe,
                score=seg.score,
                razoes=seg.razoes,
                markers=seg.markers,
                features=seg.features,
                decision=d.decision,
                adj_start_s=d.start_s,
                adj_end_s=d.end_s,
            )

    @app.get("/media/{media_id}/events", response_model=list[EventOut])
    def media_events(media_id: int) -> list[EventOut]:
        """Eventos de áudio (fala, sons, grito) em ordem de tempo; a relevância fica de fora."""
        with open_db(settings.db_path) as db:
            if db.get(MediaFile, media_id) is None:
                raise HTTPException(404, "arquivo não encontrado")
            return [
                EventOut(
                    stage=s.stage,
                    variant=s.variant,
                    kind=s.event.kind,
                    start_s=s.event.evidence.start_frame / FPS,
                    end_s=s.event.evidence.end_frame / FPS,
                    source=s.event.evidence.source.value,
                    confidence=s.event.evidence.confidence,
                    quote=s.event.evidence.quote,
                )
                for s in load_stored_events(db, media_id)
                if s.stage != "relevance"
            ]

    @app.get("/media/{media_id}/waveform", response_model=WaveformOut)
    def media_waveform(media_id: int, points: int = Query(800, ge=10, le=4000)) -> WaveformOut:
        with open_db(settings.db_path) as db:
            if db.get(MediaFile, media_id) is None:
                raise HTTPException(404, "arquivo não encontrado")
            artifact = db.scalar(
                select(Artifact).where(
                    Artifact.media_file_id == media_id,
                    Artifact.stage == "audio_signals",
                    Artifact.variant == "",
                )
            )
            if artifact is None or not Path(artifact.result_path).is_file():
                raise HTTPException(404, "sinais de áudio ainda não calculados")
            result = StageResult.model_validate_json(Path(artifact.result_path).read_text(encoding="utf-8"))
        metas = signal_metas(result)
        out: dict[str, list[float]] = {"game": [], "mic": []}
        duration = 0.0
        for key, name in (("game", "game.energy_db"), ("mic", "mic.energy_db")):
            meta = metas.get(name)
            if meta is None:
                continue
            sig = load_signal(meta)
            out[key] = _envelope(np.asarray(sig.values), points)
            duration = max(duration, sig.end_frame / FPS)
        return WaveformOut(duration_s=duration, points=points, game=out["game"], mic=out["mic"])

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
