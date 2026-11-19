"""Mídia: segmentos e decisões, eventos de áudio, forma de onda e vídeo."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.api.context import ApiContext
from cronista.api.schemas import (
    DecisionIn,
    EventOut,
    SegmentOut,
    WaveformOut,
)
from cronista.audio.events import load_stored_events
from cronista.audio.signals import load_signal, signal_metas
from cronista.db.models import Artifact, MediaFile
from cronista.domain.frames import FPS
from cronista.domain.models import StageResult
from cronista.montage import SessionPlanError, load_source
from cronista.relevance.service import STAGE as RELEVANCE_STAGE
from cronista.relevance.service import load_segments
from cronista.review.decisions import current_decisions, decision_for, record_decision


def _envelope(values: np.ndarray, points: int) -> list[float]:
    if len(values) == 0:
        return []
    buckets = np.array_split(np.asarray(values, dtype=np.float32), min(points, len(values)))
    return [round(float(b.max()), 1) for b in buckets]


def _media_duration(db: Session, media_id: int) -> float | None:
    media = db.get(MediaFile, media_id)
    try:
        return load_source(db, media).duration_s if media else None
    except SessionPlanError:
        return None  # ainda não ingerido: sem duração para conferir


def media_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()

    @router.get("/media/{media_id}/segments", response_model=list[SegmentOut])
    def media_segments(media_id: int) -> list[SegmentOut]:
        with ctx.connect() as db:
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
                    decision=d.decision if (d := decision_for(decisions, g)) else None,
                    adj_start_s=d.start_s if d else None,
                    adj_end_s=d.end_s if d else None,
                )
                for g in load_segments(db, media_id)
            ]

    @router.post("/media/{media_id}/segments/{seg_start_s}/decision", response_model=SegmentOut)
    def decide_segment(media_id: int, seg_start_s: int, body: DecisionIn) -> SegmentOut:
        """Aceita, rejeita ou ajusta os limites de um segmento. Só insere (histórico preservado)."""
        with ctx.connect() as db:
            if db.get(MediaFile, media_id) is None:
                raise HTTPException(404, "arquivo não encontrado")
            seg = next((g for g in load_segments(db, media_id) if g.start_s == seg_start_s), None)
            if seg is None:
                raise HTTPException(404, "segmento não encontrado")
            try:
                d = record_decision(
                    db,
                    media_id,
                    seg_start_s,
                    body.decision,
                    body.start_s,
                    body.end_s,
                    seg_end_s=seg.end_s,
                    duration_s=_media_duration(db, media_id),
                )
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

    @router.get("/media/{media_id}/events", response_model=list[EventOut])
    def media_events(media_id: int) -> list[EventOut]:
        """Eventos de áudio (fala, sons, grito) em ordem de tempo; a relevância fica de fora."""
        with ctx.connect() as db:
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
                if s.stage != RELEVANCE_STAGE
            ]

    @router.get("/media/{media_id}/waveform", response_model=WaveformOut)
    def media_waveform(media_id: int, points: int = Query(800, ge=10, le=4000)) -> WaveformOut:
        with ctx.connect() as db:
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

    @router.get("/media/{media_id}/video")
    def media_video(media_id: int) -> FileResponse:
        """Master normalizado (H.264 MP4); o FileResponse atende `Range`, então o player pode buscar."""
        with ctx.connect() as db:
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

    return router
