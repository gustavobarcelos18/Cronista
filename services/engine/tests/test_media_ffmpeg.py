"""T2: FFmpeg num único lugar (`media/ffmpeg`)."""

from __future__ import annotations

import io
import pathlib
import subprocess
from pathlib import Path
from typing import Any

import pytest

from cronista.config import Settings
from cronista.media import ffmpeg
from cronista.pipeline.stage import StageError


@pytest.fixture
def cfg(tmp_path: Path) -> Settings:
    return Settings(env="t", data_dir=tmp_path)


def test_base_command_is_built_in_one_place(cfg: Settings) -> None:
    assert ffmpeg.ffmpeg_cmd(cfg, ["-i", "a"]) == [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        "a",
    ]
    assert "-y" not in ffmpeg.ffmpeg_cmd(cfg, [], overwrite=False)


def test_only_media_ffmpeg_builds_the_base_command() -> None:
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "cronista"
    offenders = [
        p.relative_to(src).as_posix()
        for p in src.rglob("*.py")
        if '"-hide_banner"' in p.read_text(encoding="utf-8") and p.name != "ffmpeg.py"
    ]
    assert offenders == []


def test_video_args_same_encoder_two_qualities(cfg: Settings) -> None:
    assert ffmpeg.video_args(cfg)[:2] == ["-c:v", "libx264"] and "veryfast" in ffmpeg.video_args(cfg)
    assert "medium" in ffmpeg.video_args(cfg, "delivery")
    gpu = cfg.model_copy(update={"preview_encoder": "h264_nvenc"})
    assert "-cq" in ffmpeg.video_args(gpu) and str(cfg.preview_crf) in ffmpeg.video_args(gpu)
    delivery = ffmpeg.video_args(gpu, "delivery")
    assert delivery[delivery.index("-cq") + 1] == "19"


def test_run_ffmpeg_reports_the_tail_of_stderr(cfg: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, "", "x" * 900 + "motivo real")

    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(StageError, match="motivo real"):
        ffmpeg.run_ffmpeg(cfg, ["-i", "a"])


class _Proc:
    def __init__(self, data: bytes, code: int) -> None:
        self.stdout = io.BytesIO(data)
        self._code = code

    def wait(self) -> int:
        return self._code


def test_pipe_raw_yields_whole_frames_and_drops_the_partial_tail(
    cfg: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _Proc(b"a" * 10 + b"b" * 10 + b"c" * 3, 0))
    out = list(ffmpeg.pipe_raw(cfg, ["-f", "rawvideo", "-"], chunk_bytes=20, unit_bytes=10))
    assert out == [b"a" * 10 + b"b" * 10]  # os 3 bytes finais não formam um quadro


def test_pipe_raw_raises_when_ffmpeg_fails(cfg: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _Proc(b"", 1))
    with pytest.raises(StageError, match="ler quadros"):
        list(ffmpeg.pipe_raw(cfg, [], chunk_bytes=10))
