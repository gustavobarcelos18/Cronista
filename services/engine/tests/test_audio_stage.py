"""Etapa de áudio: RF64 acima de 4 GB, leitura única do master e faixa certa em cada WAV."""

from __future__ import annotations

import array
import itertools
import wave
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from cronista.config import Settings
from cronista.domain.models import StageResult
from cronista.ingest import stages
from cronista.ingest.service import ingest_folder
from cronista.ingest.stages import AUDIO_TRACKS, AudioStage, audio_extract_args
from cronista.pipeline import AlwaysFreeGate, StageContext
from tests.conftest import needs_ffmpeg


def test_extract_args_read_master_once_and_allow_rf64() -> None:
    args = audio_extract_args(Path("master.mp4"), [(1, Path("game.wav")), (2, Path("mic.wav"))])
    assert args.count("-i") == 1
    assert args.count("-rf64") == 2
    assert args[args.index("-rf64") + 1] == "auto"
    assert [args[i + 1] for i, arg in enumerate(args) if arg == "-map"] == ["0:a:1", "0:a:2"]
    assert args[-1] == "mic.wav"


def test_mix_is_never_extracted() -> None:
    assert [index for _, index in AUDIO_TRACKS] == [1, 2]  # 0 = mix (CLAUDE.md: nunca analisar o mix)


def test_stage_calls_ffmpeg_once(monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(stages, "run_ffmpeg", lambda _settings, args: calls.append(args))
    ctx = StageContext(
        media_path=tmp_path / "master.mp4",
        out_dir=tmp_path,
        settings=settings,
        inputs={"normalize": StageResult(data={"media": str(tmp_path / "master.mp4")})},
    )
    result = AudioStage().run(ctx)
    assert len(calls) == 1
    assert result.data == {"game": str(tmp_path / "game.wav"), "mic": str(tmp_path / "mic.wav")}
    assert result.files == list(result.data.values())


def _dominant_frequency(path: Path) -> float:
    """Frequência de um tom puro pelos cruzamentos por zero no primeiro segundo."""
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        frames = handle.readframes(handle.getframerate())
    samples = array.array("h", frames)[::channels]
    return sum(1 for a, b in itertools.pairwise(samples) if (a < 0) != (b < 0)) / 2


@needs_ffmpeg
def test_each_wav_comes_from_its_track(
    db: Session, settings: Settings, fixture_folders: dict[str, Path]
) -> None:
    """Fixtures: faixa 1 (mix) 440 Hz, faixa 2 (jogo) 660 Hz, faixa 3 (microfone) 880 Hz."""
    report = ingest_folder(db, fixture_folders["normal"], settings, AlwaysFreeGate())
    assert report.ok, report.failures
    (result,) = report.files.values()
    audio = result.results["audio"].data

    for label, expected in (("game", 660), ("mic", 880)):
        wav = Path(str(audio[label]))
        assert wav.read_bytes()[:4] == b"RIFF"  # abaixo de 4 GB continua WAV comum
        assert _dominant_frequency(wav) == pytest.approx(expected, rel=0.05), label
