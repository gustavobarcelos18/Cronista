"""Timelapses pré-renderizados com FFmpeg (plano 6.3): sem áudio, 60 fps, nada do Studio (sem Speed Warp)."""

from __future__ import annotations

from collections.abc import Mapping
from functools import partial
from pathlib import Path

from cronista.assembly.plan import EditItem, EditPlan, Mode, Track
from cronista.config import Settings
from cronista.domain.frames import FPS
from cronista.finishing.render.atomic import render_to
from cronista.ingest.ffmpeg import run_ffmpeg
from cronista.pipeline.gpu import GpuGate, wait_until_free


def _render(settings: Settings, master: Path, item: EditItem, out: Path) -> None:
    run_ffmpeg(
        settings,
        [
            "-ss", f"{item.in_frame / FPS:.6f}",
            "-t", f"{item.source_frames / FPS:.6f}",
            "-i", str(master),
            "-an",
            "-vf", f"setpts=PTS/{item.speed},fps={FPS}",
            "-frames:v", str(item.timeline_frames),
            "-c:v", settings.preview_encoder,
            "-pix_fmt", "yuv420p",
            str(out),
        ],
    )  # fmt: skip


def render_timelapses(
    plan: EditPlan,
    masters: Mapping[int, Path],
    out_dir: Path,
    settings: Settings,
    gate: GpuGate | None = None,
) -> dict[int, Path]:
    """Um MP4 por item de timelapse (índice do item no plano → arquivo). Reaproveita o que já existe."""
    out_dir.mkdir(parents=True, exist_ok=True)
    done: dict[int, Path] = {}
    for n, item in enumerate(plan.items):
        if item.track != Track.V1 or item.mode != Mode.TIMELAPSE:
            continue
        target = out_dir / f"tl-{item.file_id}-{item.in_frame}-{item.out_frame}-x{item.speed}.mp4"
        if not target.is_file() or target.stat().st_size == 0:
            if gate is not None:  # a GPU é a mesma do OBS e do jogo: espera antes de cada render
                wait_until_free(gate, settings.gpu_poll_seconds, etapa="timelapse", arquivo=target.name)
            # Atômico: um render interrompido não pode deixar um MP4 parcial com o nome final.
            render_to(target, partial(_render, settings, masters[item.file_id], item))
        done[n] = target
    return done
