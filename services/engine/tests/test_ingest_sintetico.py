"""A14: ingestão com bytes e saídas sintéticas, sem FFmpeg (roda em qualquer máquina)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cronista.config import Settings
from cronista.ingest.ffmpeg import is_unfinalized_mp4, probe_chapters, probe_media


def _box(kind: bytes, payload: bytes = b"") -> bytes:
    return (8 + len(payload)).to_bytes(4, "big") + kind + payload


def _mp4(tmp_path: Path, data: bytes, name: str = "a.mp4") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_finalized_mp4_is_not_flagged(tmp_path: Path) -> None:
    assert not is_unfinalized_mp4(
        _mp4(tmp_path, _box(b"ftyp", b"isom") + _box(b"moov") + _box(b"mdat", b"x" * 8))
    )


def test_empty_file_is_unfinalized(tmp_path: Path) -> None:
    assert is_unfinalized_mp4(_mp4(tmp_path, b""))


def test_fragmented_mp4_with_moof_is_unfinalized(tmp_path: Path) -> None:
    assert is_unfinalized_mp4(_mp4(tmp_path, _box(b"ftyp", b"isom") + _box(b"moov") + _box(b"moof")))


def test_file_without_moov_is_unfinalized(tmp_path: Path) -> None:
    assert is_unfinalized_mp4(_mp4(tmp_path, _box(b"ftyp", b"isom") + _box(b"mdat", b"x" * 8)))


def test_box_larger_than_the_file_is_unfinalized(tmp_path: Path) -> None:
    truncated = (1000).to_bytes(4, "big") + b"mdat" + b"x" * 8
    assert is_unfinalized_mp4(_mp4(tmp_path, _box(b"ftyp", b"isom") + _box(b"moov") + truncated))


def test_64_bit_box_is_read_with_its_extended_size(tmp_path: Path) -> None:
    payload = b"x" * 8
    big = (1).to_bytes(4, "big") + b"mdat" + (16 + len(payload)).to_bytes(8, "big") + payload
    assert not is_unfinalized_mp4(_mp4(tmp_path, _box(b"ftyp", b"isom") + _box(b"moov") + big))


def test_non_mp4_container_is_never_flagged(tmp_path: Path) -> None:
    assert not is_unfinalized_mp4(_mp4(tmp_path, b"", "gravacao.mkv"))


def _fake_ffprobe(monkeypatch: pytest.MonkeyPatch, stdout: str, returncode: int = 0) -> None:
    def run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", run)


def test_probe_chapters_with_invalid_json_returns_empty(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp_path: Path
) -> None:
    _fake_ffprobe(monkeypatch, '{"chapters": [')
    assert probe_chapters(settings, tmp_path / "a.mp4") == []


def test_probe_chapters_reads_title_and_start_in_frames(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp_path: Path
) -> None:
    _fake_ffprobe(monkeypatch, '{"chapters": [{"start_time": "2.0", "tags": {"title": "Novo dia"}}]}')
    [chapter] = probe_chapters(settings, tmp_path / "a.mp4")
    assert chapter.title == "Novo dia" and chapter.media_frame == 120


def test_probe_media_with_truncated_json_is_interrupted(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp_path: Path
) -> None:
    _fake_ffprobe(monkeypatch, '{"streams": [')
    assert probe_media(settings, tmp_path / "a.mp4").interrupted


def test_probe_media_counts_the_audio_tracks(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp_path: Path
) -> None:
    video = '{"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "r_frame_rate": "60/1"}'
    audio = '{"codec_type": "audio"}'
    _fake_ffprobe(monkeypatch, f'{{"streams": [{video}, {audio}, {audio}], "format": {{"duration": "9.5"}}}}')
    probe = probe_media(settings, _mp4(tmp_path, _box(b"ftyp") + _box(b"moov")))
    assert probe.audio_streams == 2 and not probe.interrupted
