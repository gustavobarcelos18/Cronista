"""Plano de montagem de uma sessão: marcadores → janelas + os arquivos de onde elas saem.

Usado pela prévia MP4 e pela exportação legada (`cronista export`, deprecada); a montagem principal para o
Resolve usa `assembly/` e a `story`. Também é a porta de leitura dos masters (`load_source`, `load_masters`).
Lê só o banco e os artefatos da ingestão; não roda FFmpeg.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.config import Settings
from cronista.db.models import Artifact, Marker, MediaFile, RecordingSession
from cronista.domain.frames import frame_to_seconds
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
    artifact = db.scalar(
        select(Artifact).where(
            Artifact.media_file_id == media.id, Artifact.stage == stage, Artifact.variant == ""
        )
    )
    if artifact is None or not Path(artifact.result_path).is_file():
        return None
    return StageResult.model_validate_json(Path(artifact.result_path).read_text(encoding="utf-8"))


def _probe_duration(normalized: StageResult | None) -> float | None:
    duration = normalized.data.get("probe", {}).get("duration_s") if normalized else None
    return float(duration) if duration is not None else None


def recorded_duration(db: Session, media: MediaFile) -> float | None:
    """Duração medida na ingestão, independente dos cortes ou da disponibilidade do master."""
    return _probe_duration(_artifact_result(db, media, "normalize"))


def load_source(db: Session, media: MediaFile) -> SourceFile:
    normalized = _artifact_result(db, media, "normalize")
    if normalized is None:
        raise SessionPlanError(f"{Path(media.path).name} ainda não foi ingerido (rode `cronista ingest`)")
    master = Path(str(normalized.data["media"]))
    if not master.is_file():
        raise SessionPlanError(f"{master} não existe mais; rode `cronista ingest` de novo")
    duration = _probe_duration(normalized)

    audio = _artifact_result(db, media, "audio")

    def wav(label: str) -> Path | None:
        if audio is None:
            return None
        path = Path(str(audio.data.get(label, "")))
        return path if path.is_file() else None

    return SourceFile(media.id, master, duration, wav("game"), wav("mic"))


def load_masters(
    db: Session, session: RecordingSession, project_wide: bool = False
) -> tuple[dict[int, Path], list[str]]:
    """Master de cada gravação da sessão (ou de todas as do projeto, no vídeo da série). Gravação sem
    ingestão vira aviso (quem precisar dela a ignora); só falha se nenhuma gravação estiver pronta."""
    masters: dict[int, Path] = {}
    notes: list[str] = []
    sessions = list(session.project.sessions) if project_wide else [session]
    for media in (m for s in sessions for m in s.media_files):
        try:
            masters[media.id] = load_source(db, media).master
        except SessionPlanError as exc:
            notes.append(str(exc))
    if not masters:
        raise SessionPlanError(notes[0] if notes else f"sessão {session.id} não tem gravações")
    return masters, notes


def plan_session(db: Session, session_id: int, settings: Settings) -> SessionPlan:
    session = db.get(RecordingSession, session_id)
    if session is None:
        raise SessionPlanError(f"sessão {session_id} não existe (veja `cronista status`)")
    markers = list(db.scalars(select(Marker).where(Marker.session_id == session_id)))
    if not markers:
        raise SessionPlanError(f"sessão {session_id} não tem marcadores")

    # Como em `load_masters`: gravação sem ingestão vira aviso; só falha se nenhuma estiver pronta.
    sources: dict[int, SourceFile] = {}
    notes: list[str] = []
    for media in session.media_files:
        try:
            sources[media.id] = load_source(db, media)
        except SessionPlanError as exc:
            notes.append(str(exc))
    if not sources:
        raise SessionPlanError(notes[0] if notes else f"sessão {session_id} não tem gravações")
    ordinals = {media.id: media.ordinal for media in session.media_files}

    points: list[MarkerPoint] = []
    for m in markers:
        if m.media_file_id is not None and m.media_file_id in sources:
            duration = sources[m.media_file_id].duration_s
            points.append(
                MarkerPoint(
                    m.marker_id,
                    MarkerKind(m.kind),
                    m.media_file_id,
                    frame_to_seconds(m.media_frame),
                    duration,
                )
            )
    points.sort(key=lambda p: (ordinals[p.file_id], p.time_s))
    windows, warnings = plan_windows(points, settings.preview_pre_s, settings.preview_post_s)
    if not windows:
        raise SessionPlanError("nenhum marcador gerou trecho utilizável")
    return SessionPlan(session_id, windows, sources, [*notes, *warnings])
