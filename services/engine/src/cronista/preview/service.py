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

from sqlalchemy.orm import Session

from cronista.config import Settings
from cronista.domain.preview import ClipWindow, expected_duration_s
from cronista.ingest.ffmpeg import probe_media
from cronista.logging_setup import log_event
from cronista.media.ffmpeg import run_ffmpeg, video_args
from cronista.montage import SessionPlanError, plan_session
from cronista.pipeline import GpuGate, StageError, wait_until_free

PREVIEW_FPS = "60"
PREVIEW_SIZE = "1920:1080"


PreviewError = SessionPlanError


@dataclass
class PreviewReport:
    path: Path
    clips: int
    expected_s: float
    actual_s: float | None
    warnings: list[str] = field(default_factory=list)


def _concat_line(path: Path) -> str:
    escaped = path.as_posix().replace("'", "'\\''")
    return f"file '{escaped}'"


def _cut(settings: Settings, source: Path, window: ClipWindow, out: Path) -> None:
    """Um trecho: `-ss` antes do `-i` com recodificação é preciso no quadro e rápido em arquivo grande."""
    run_ffmpeg(
        settings,
        ["-ss", f"{window.start_s:.3f}", "-t", f"{window.duration_s:.3f}", "-i", str(source),
         "-map", "0:v:0", "-map", "0:a:0",
         "-vf", f"scale={PREVIEW_SIZE},fps={PREVIEW_FPS},format=yuv420p",
         *video_args(settings), "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(out)],
    )  # fmt: skip


def build_preview(
    db: Session,
    session_id: int,
    settings: Settings,
    gate: GpuGate,
    out: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> PreviewReport:
    plan = plan_session(db, session_id, settings)
    windows, warnings = plan.windows, plan.warnings

    def wait_for_gpu(working: bool) -> None:
        wait_until_free(
            gate, settings.gpu_poll_seconds, sleep, working=working, session_id=session_id, stage="preview"
        )

    wait_for_gpu(working=False)  # a prévia também é processamento: pausa com o OBS gravando ou jogo aberto

    target = out or settings.data_dir / "previews" / f"sessao-{session_id}.mp4"
    target.parent.mkdir(parents=True, exist_ok=True)
    work = settings.cache_dir / "preview" / str(session_id)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    try:
        clips: list[Path] = []
        for index, window in enumerate(windows):
            wait_for_gpu(working=True)  # um jogo pode abrir no meio: pausa entre os trechos
            clip = work / f"{index:04d}.mp4"
            try:
                _cut(settings, plan.sources[window.file_id].master, window, clip)
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
