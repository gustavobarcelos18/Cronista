"""Relevância de uma sessão: lê eventos e marcadores do banco, grava os segmentos como eventos `segmento`."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.audio.events import load_active_events, load_events, replace_events
from cronista.db.models import Marker, MediaFile, RecordingSession
from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource, params_hash
from cronista.domain.frames import FPS, frame_to_seconds
from cronista.relevance.engine import MarkerRef, RelevanceParams, Segment, build_segments

STAGE = "relevance"
MODEL = "relevancia-regras"
MODEL_VERSION = "1"
TIMELAPSE_FACTOR = 10.0
MAX_KEPT_S = 45.0
MAX_FARM_S = 20.0


class RelevanceError(Exception):
    pass


@dataclass
class FileRelevance:
    file_id: int
    name: str
    segments: list[Segment] = field(default_factory=list)


def segments_to_events(segments: list[Segment], params: RelevanceParams) -> list[AnalysisEvent]:
    digest = params_hash(params.__dict__)
    return [
        AnalysisEvent(
            kind="segmento",
            evidence=Evidence(
                source=EvidenceSource.EVENTO,
                start_frame=s.start_s * FPS,
                end_frame=s.end_s * FPS,
                confidence=s.score,
                model=MODEL,
                model_version=MODEL_VERSION,
                params_hash=digest,
            ),
            payload={"classe": s.classe, "razoes": s.razoes, "marcadores": s.markers, "features": s.features},
        )
        for s in segments
    ]


def events_to_segments(events: list[AnalysisEvent]) -> list[Segment]:
    return [
        Segment(
            e.evidence.start_frame // FPS,
            e.evidence.end_frame // FPS,
            str(e.payload["classe"]),
            e.evidence.confidence,
            list(e.payload.get("razoes", [])),
            list(e.payload.get("marcadores", [])),
            dict(e.payload.get("features", {})),
        )
        for e in events
        if e.kind == "segmento"
    ]


def relevance_session(
    db: Session, session_id: int, params: RelevanceParams | None = None
) -> list[FileRelevance]:
    """Recalcula e grava os segmentos de cada arquivo da sessão (substitui os anteriores)."""
    session = db.get(RecordingSession, session_id)
    if session is None:
        raise RelevanceError(f"sessão {session_id} não existe (veja `cronista status`)")
    if params is None:  # pesos aceitos pelo criador no Studio (7E); sem calibração, os padrão
        from cronista.review.learning import params_for_project

        params = params_for_project(db, session.project_id)
    return [_one_file(db, m, params) for m in sorted(session.media_files, key=lambda m: m.ordinal)]


def _one_file(db: Session, media: MediaFile, params: RelevanceParams) -> FileRelevance:
    events = [e for e in load_active_events(db, media.id) if e.kind != "segmento"]
    markers = [
        MarkerRef(m.marker_id, m.kind, frame_to_seconds(m.media_frame))
        for m in db.scalars(select(Marker).where(Marker.media_file_id == media.id))
    ]
    segments = build_segments(events, markers, None, params)
    replace_events(db, media.id, STAGE, "", segments_to_events(segments, params))
    return FileRelevance(media.id, media.path.replace("\\", "/").rsplit("/", 1)[-1], segments)


def load_segments(db: Session, media_id: int) -> list[Segment]:
    return events_to_segments(load_events(db, media_id, stage=STAGE))


def product_seconds(segments: list[Segment], keep_score: float = 0.35) -> float:
    """Estimativa do material mantido: trechos relevantes (cada um limitado) e farm em timelapse."""
    total = 0.0
    for s in segments:
        if s.classe == "descartavel":
            continue
        if s.classe == "farm":
            total += min(s.duration_s / TIMELAPSE_FACTOR, MAX_FARM_S)
        elif s.score >= keep_score:
            total += min(float(s.duration_s), MAX_KEPT_S)
    return total


def series_panel(db: Session) -> list[dict[str, float | int]]:
    """Painel da série: por sessão, horas gravadas e minutos estimados de produto, e o acumulado."""
    rows: list[dict[str, float | int]] = []
    cumulative = 0.0
    for session in db.scalars(select(RecordingSession).order_by(RecordingSession.id)):
        raw = kept = 0.0
        for media in session.media_files:
            segs = load_segments(db, media.id)
            if segs:
                raw += max(s.end_s for s in segs)
                kept += product_seconds(segs)
        cumulative += kept
        rows.append(
            {
                "sessao": session.id,
                "gravado_h": round(raw / 3600, 2),
                "produto_min": round(kept / 60, 1),
                "acumulado_min": round(cumulative / 60, 1),
            }
        )
    return rows
