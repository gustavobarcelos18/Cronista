"""`cronista preview <sessão>`: corta uma janela ao redor de cada marcador e concatena em 1080p60 H.264.

Áudio da prévia = o mix (faixa 1), nunca as faixas de análise. Sem recursos do Studio. Em `dev` o
encoder é CPU (libx264); em `prod`, NVENC, e então o trabalho espera a `GpuGate` liberar.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.config import Settings
from cronista.db.models import Artifact, Marker, MediaFile, RecordingSession
from cronista.domain.models import MarkerKind, StageResult
from cronista.domain.preview import ClipWindow, MarkerPoint, expected_duration_s, plan_windows
from cronista.ingest.ffmpeg import probe_media, run_ffmpeg
from cronista.logging_setup import log_event
from cronista.pipeline import GpuGate, StageError

PREVIEW_FPS = "60"
PREVIEW_SIZE = "1920:1080"


class PreviewError(Exception):
    """Sessão inexistente, sem arquivos ingeridos, sem marcadores ou sem trechos utilizáveis."""


@dataclass
class PreviewReport:
    path: Path
    clips: int
    expected_s: float
    actual_s: float | None
    warnings: list[str] = field(default_factory=list)


def _video_args(settings: Settings) -> list[str]:
    encoder = settings.preview_encoder
    if encoder.endswith("_nvenc"):
        return ["-c:v", encoder, "-preset", "p5", "-rc", "vbr", "-cq", str(settings.preview_crf), "-b:v", "0"]
    return ["-c:v", encoder, "-preset", "veryfast", "-crf", str(settings.preview_crf)]


def _concat_line(path: Path) -> str:
    escaped = path.as_posix().replace("'", "'\\''")
    return f"file '{escaped}'"


def _load_normalized(db: Session, media: MediaFile) -> tuple[Path, float | None]:
    artifact = db.scalar(
        select(Artifact).where(Artifact.media_file_id == media.id, Artifact.stage == "normalize")
    )
    if artifact is None or not Path(artifact.result_path).is_file():
        raise PreviewError(f"{Path(media.path).name} ainda não foi ingerido (rode `cronista ingest`)")
    result = StageResult.model_validate_json(Path(artifact.result_path).read_text(encoding="utf-8"))
    path = Path(str(result.data["media"]))
    if not path.is_file():
        raise PreviewError(f"{path} não existe mais; rode `cronista ingest` de novo")
    duration = result.data["probe"].get("duration_s")
    return path, float(duration) if duration is not None else None


def _cut(settings: Settings, source: Path, window: ClipWindow, out: Path) -> None:
    """Um trecho: `-ss` antes do `-i` com recodificação é preciso no quadro e rápido em arquivo grande."""
    run_ffmpeg(
        settings,
        ["-ss", f"{window.start_s:.3f}", "-t", f"{window.duration_s:.3f}", "-i", str(source),
         "-map", "0:v:0", "-map", "0:a:0",
         "-vf", f"scale={PREVIEW_SIZE},fps={PREVIEW_FPS},format=yuv420p",
         *_video_args(settings), "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(out)],
    )  # fmt: skip


def build_preview(
    db: Session,
    session_id: int,
    settings: Settings,
    gate: GpuGate,
    out: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> PreviewReport:
    session = db.get(RecordingSession, session_id)
    if session is None:
        raise PreviewError(f"sessão {session_id} não existe (veja `cronista status`)")
    markers = list(db.scalars(select(Marker).where(Marker.session_id == session_id)))
    if not markers:
        raise PreviewError(f"sessão {session_id} não tem marcadores")

    sources: dict[int, tuple[Path, float | None]] = {}
    ordinals: dict[int, int] = {}
    for media in session.media_files:
        sources[media.id] = _load_normalized(db, media)
        ordinals[media.id] = media.ordinal

    points: list[MarkerPoint] = []
    for m in markers:
        if m.media_file_id is not None and m.media_file_id in sources:
            duration = sources[m.media_file_id][1]
            points.append(
                MarkerPoint(m.marker_id, MarkerKind(m.kind), m.media_file_id, m.media_time_s, duration)
            )
    points.sort(key=lambda p: (ordinals[p.file_id], p.time_s))
    windows, warnings = plan_windows(points, settings.preview_pre_s, settings.preview_post_s)
    if not windows:
        raise PreviewError("nenhum marcador gerou trecho utilizável")

    if settings.preview_encoder.endswith("_nvenc"):
        while not gate.is_free():
            log_event("gpu_ocupada_aguardando", session_id=session_id, stage="preview")
            sleep(settings.gpu_poll_seconds)

    target = out or settings.data_dir / "previews" / f"sessao-{session_id}.mp4"
    target.parent.mkdir(parents=True, exist_ok=True)
    work = settings.cache_dir / "preview" / str(session_id)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    try:
        clips: list[Path] = []
        for index, window in enumerate(windows):
            clip = work / f"{index:04d}.mp4"
            try:
                _cut(settings, sources[window.file_id][0], window, clip)
            except StageError as exc:
                raise PreviewError(f"trecho do marcador {window.marker_id}: {exc}") from exc
            clips.append(clip)
        listing = work / "concat.txt"
        listing.write_text("\n".join(_concat_line(c) for c in clips) + "\n", encoding="utf-8")
        try:
            run_ffmpeg(
                settings,
                ["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart",
                 str(target)],
            )  # fmt: skip
        except StageError as exc:
            raise PreviewError(f"concatenação falhou: {exc}") from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)

    expected = expected_duration_s(windows)
    actual = probe_media(settings, target).duration_s
    log_event("previa_gerada", session_id=session_id, clips=len(windows), path=str(target))
    return PreviewReport(target, len(windows), expected, actual, warnings)
