"""Prévia MP4: planejamento das janelas (puro) e geração sobre fixtures reais do FFmpeg."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from cronista.config import Settings
from cronista.db.models import Marker, MediaFile, RecordingSession
from cronista.domain.models import MarkerKind
from cronista.domain.preview import MarkerPoint, expected_duration_s, plan_windows
from cronista.ingest.service import ingest_folder
from cronista.pipeline import AlwaysFreeGate
from cronista.preview import PreviewError, build_preview
from tests.conftest import needs_ffmpeg


def _point(marker_id: str, time_s: float, duration: float | None = 100.0, file_id: int = 1) -> MarkerPoint:
    return MarkerPoint(marker_id, MarkerKind.MOMENTO, file_id, time_s, duration)


def test_window_is_20s_before_and_10s_after() -> None:
    windows, warnings = plan_windows([_point("a", 50.0)], pre_s=20, post_s=10)
    assert warnings == []
    assert (windows[0].start_s, windows[0].end_s, windows[0].duration_s) == (30.0, 60.0, 30.0)


def test_window_is_clamped_to_file_bounds() -> None:
    windows, _ = plan_windows([_point("ini", 5.0), _point("fim", 98.0)], pre_s=20, post_s=10)
    assert [(w.start_s, w.end_s) for w in windows] == [(0.0, 15.0), (78.0, 100.0)]


def test_unknown_duration_does_not_clamp_the_end() -> None:
    windows, _ = plan_windows([_point("a", 50.0, duration=None)], pre_s=20, post_s=10)
    assert windows[0].end_s == 60.0


def test_marker_past_end_of_file_is_dropped_with_warning() -> None:
    windows, warnings = plan_windows([_point("longe", 500.0), _point("ok", 50.0)], pre_s=20, post_s=10)
    assert [w.marker_id for w in windows] == ["ok"]
    assert len(warnings) == 1 and "longe" in warnings[0]


def test_overlapping_windows_are_kept_one_clip_per_marker() -> None:
    windows, _ = plan_windows([_point("a", 50.0), _point("b", 52.0)], pre_s=20, post_s=10)
    assert len(windows) == 2
    assert expected_duration_s(windows) == pytest.approx(60.0)


# --- geração (FFmpeg) ---


def _stream_info(settings: Settings, path: Path) -> dict[str, object]:
    cmd = [
        settings.ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    info: dict[str, object] = json.loads(out)
    return info


def _put_markers(db: Session, session_id: int, rows: list[tuple[int, str, int]]) -> None:
    """Troca os marcadores da sessão por (id do arquivo, marker_id, quadro a 60 fps)."""
    db.execute(delete(Marker).where(Marker.session_id == session_id))
    for media_id, marker_id, frame in rows:
        db.add(
            Marker(
                session_id=session_id,
                media_file_id=media_id,
                marker_id=marker_id,
                kind="momento",
                media_frame=frame,
            )
        )
    db.commit()


@needs_ffmpeg
def test_preview_has_one_clip_per_marker_and_expected_duration(
    db: Session, settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    report = ingest_folder(db, fixture_folders["split"], settings, AlwaysFreeGate(), "p")
    assert report.ok
    files = db.query(MediaFile).order_by(MediaFile.ordinal).all()
    _put_markers(
        db, report.session_id, [(files[0].id, "a", 60), (files[1].id, "b", 30), (files[1].id, "c", 90)]
    )

    out = tmp_path / "previa.mp4"
    result = build_preview(db, report.session_id, settings, AlwaysFreeGate(), out)

    # Cada fixture dura 2 s: todas as janelas (20 s antes / 10 s depois) caem no arquivo inteiro.
    assert result.clips == 3
    assert result.expected_s == pytest.approx(6.0)
    assert result.actual_s == pytest.approx(result.expected_s, abs=1.0)
    assert result.path == out and out.is_file()

    info = _stream_info(settings, out)
    streams: list[dict[str, object]] = info["streams"]  # type: ignore[assignment]
    video = next(s for s in streams if s["codec_type"] == "video")
    assert (video["codec_name"], video["width"], video["height"], video["r_frame_rate"]) == (
        "h264",
        1920,
        1080,
        "60/1",
    )
    assert sum(1 for s in streams if s["codec_type"] == "audio") == 1  # só o mix


@needs_ffmpeg
def test_preview_leaves_no_work_files_and_is_repeatable(
    db: Session, settings: Settings, fixture_folders: dict[str, Path]
) -> None:
    report = ingest_folder(db, fixture_folders["normal"], settings, AlwaysFreeGate(), "p")
    first = build_preview(db, report.session_id, settings, AlwaysFreeGate())
    second = build_preview(db, report.session_id, settings, AlwaysFreeGate())
    assert first.path == second.path == settings.data_dir / "previews" / f"sessao-{report.session_id}.mp4"
    assert not (settings.cache_dir / "preview" / str(report.session_id)).exists()


@needs_ffmpeg
def test_preview_waits_for_the_gate_before_starting_and_between_clips(
    db: Session, settings: Settings, fixture_folders: dict[str, Path]
) -> None:
    report = ingest_folder(db, fixture_folders["normal"], settings, AlwaysFreeGate(), "p")
    checks: list[str] = []

    class Gate:
        def __init__(self) -> None:
            self.busy_left = 2

        def is_free(self) -> bool:
            checks.append("antes")
            self.busy_left -= 1
            return self.busy_left < 0

        def is_free_while_working(self) -> bool:
            checks.append("entre")
            return True

    naps: list[float] = []
    result = build_preview(db, report.session_id, settings, Gate(), sleep=naps.append)
    assert len(naps) == 2  # esperou o gate antes de começar (o encoder é de CPU, mas é processamento)
    assert checks == ["antes", "antes", "antes", "entre"]  # e olhou de novo antes do único trecho
    assert result.clips == 1


def test_preview_errors_are_clear(db: Session, settings: Settings) -> None:
    with pytest.raises(PreviewError, match="não existe"):
        build_preview(db, 99, settings, AlwaysFreeGate())


@needs_ffmpeg
def test_preview_requires_markers(db: Session, settings: Settings, fixture_folders: dict[str, Path]) -> None:
    report = ingest_folder(db, fixture_folders["normal"], settings, AlwaysFreeGate(), "p")
    _put_markers(db, report.session_id, [])
    with pytest.raises(PreviewError, match="não tem marcadores"):
        build_preview(db, report.session_id, settings, AlwaysFreeGate())


@needs_ffmpeg
def test_preview_requires_ingested_files(db: Session, settings: Settings, tmp_path: Path) -> None:
    from cronista.db.models import Project

    project = Project(name="p")
    db.add(project)
    db.flush()
    session = RecordingSession(project_id=project.id, folder=str(tmp_path))
    db.add(session)
    db.flush()
    media = MediaFile(session_id=session.id, path=str(tmp_path / "x.mp4"), ordinal=0)
    db.add(media)
    db.commit()
    _put_markers(db, session.id, [(media.id, "a", 60)])
    with pytest.raises(PreviewError, match="não foi ingerido"):
        build_preview(db, session.id, settings, AlwaysFreeGate())
