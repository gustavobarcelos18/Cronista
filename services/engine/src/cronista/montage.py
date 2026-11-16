"""Plano de montagem de uma sessão: marcadores → janelas + os arquivos de onde elas saem.

Compartilhado pela prévia MP4 e pela exportação para o Resolve, para os dois usarem exatamente os mesmos
trechos. Lê só o banco e os artefatos da ingestão; não roda FFmpeg.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.config import Settings
from cronista.db.models import Artifact, Marker, MediaFile, RecordingSession
from cronista.domain.models import MarkerKind, StageResult
from cronista.domain.preview import ClipWindow, MarkerPoint, plan_windows


class SessionPlanError(Exception):
    """Sessão inexistente, sem arquivos ingeridos, sem marcadores ou sem trechos utilizáveis."""


@dataclass(frozen=True)
class SourceFile:
    """Um master já normalizado (remuxado/8-bit) e os WAVs extraídos dele na ingestão."""

    file_id: int
    master: Path
    duration_s: float | None
    game_wav: Path | None  # faixa 2
    mic_wav: Path | None  # faixa 3


@dataclass
class SessionPlan:
    session_id: int
    windows: list[ClipWindow]
    sources: dict[int, SourceFile]
    warnings: list[str] = field(default_factory=list)


def _artifact_result(db: Session, media: MediaFile, stage: str) -> StageResult | None:
    artifact = db.scalar(select(Artifact).where(Artifact.media_file_id == media.id, Artifact.stage == stage))
    if artifact is None or not Path(artifact.result_path).is_file():
        return None
    return StageResult.model_validate_json(Path(artifact.result_path).read_text(encoding="utf-8"))


def _load_source(db: Session, media: MediaFile) -> SourceFile:
    normalized = _artifact_result(db, media, "normalize")
    if normalized is None:
        raise SessionPlanError(f"{Path(media.path).name} ainda não foi ingerido (rode `cronista ingest`)")
    master = Path(str(normalized.data["media"]))
    if not master.is_file():
        raise SessionPlanError(f"{master} não existe mais; rode `cronista ingest` de novo")
    duration = normalized.data["probe"].get("duration_s")

    audio = _artifact_result(db, media, "audio")

    def wav(label: str) -> Path | None:
        if audio is None:
            return None
        path = Path(str(audio.data.get(label, "")))
        return path if path.is_file() else None

    return SourceFile(
        media.id, master, float(duration) if duration is not None else None, wav("game"), wav("mic")
    )


def plan_session(db: Session, session_id: int, settings: Settings) -> SessionPlan:
    session = db.get(RecordingSession, session_id)
    if session is None:
        raise SessionPlanError(f"sessão {session_id} não existe (veja `cronista status`)")
    markers = list(db.scalars(select(Marker).where(Marker.session_id == session_id)))
    if not markers:
        raise SessionPlanError(f"sessão {session_id} não tem marcadores")

    sources = {media.id: _load_source(db, media) for media in session.media_files}
    ordinals = {media.id: media.ordinal for media in session.media_files}

    points: list[MarkerPoint] = []
    for m in markers:
        if m.media_file_id is not None and m.media_file_id in sources:
            duration = sources[m.media_file_id].duration_s
            points.append(
                MarkerPoint(m.marker_id, MarkerKind(m.kind), m.media_file_id, m.media_time_s, duration)
            )
    points.sort(key=lambda p: (ordinals[p.file_id], p.time_s))
    windows, warnings = plan_windows(points, settings.preview_pre_s, settings.preview_post_s)
    if not windows:
        raise SessionPlanError("nenhum marcador gerou trecho utilizável")
    return SessionPlan(session_id, windows, sources, warnings)
