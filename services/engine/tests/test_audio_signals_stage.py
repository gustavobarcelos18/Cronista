"""Etapa `audio_signals` sobre a fixture real (três faixas): ingestão → sinais, cache e uso de só 2 faixas."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.audio import dsp
from cronista.audio.signals import load_signal, signal_metas
from cronista.audio.stages import AudioSignalsStage
from cronista.config import Settings
from cronista.db.models import Artifact, MediaFile
from cronista.domain.models import StageResult
from cronista.ingest.service import ingest_folder
from cronista.ingest.stages import ingest_stages
from cronista.pipeline import AlwaysFreeGate, StageContext, StageError, run_pipeline
from tests.conftest import needs_ffmpeg

EXPECTED = {
    "game.energy_db",
    "game.onset",
    "game.novelty",
    "game.periodicity",
    "mic.energy_db",
    "mic.energy_rel_db",
}


@needs_ffmpeg
def test_stage_produces_aligned_signals_and_is_cached(
    db: Session, settings: Settings, fixture_folders: dict[str, Path]
) -> None:
    assert ingest_folder(db, fixture_folders["normal"], settings, AlwaysFreeGate()).ok
    media = db.scalars(select(MediaFile)).one()
    stages = [*ingest_stages(), AudioSignalsStage()]

    first = run_pipeline(db, media, stages, settings, AlwaysFreeGate())
    second = run_pipeline(db, media, stages, settings, AlwaysFreeGate())

    assert first.cached == ["normalize", "proxy", "audio"] and first.executed == ["audio_signals"]
    assert second.cached[-1] == "audio_signals" and second.executed == []
    metas = signal_metas(first.results["audio_signals"])
    assert set(metas) == EXPECTED
    lengths = {m.length for m in metas.values()}
    assert len(lengths) == 1  # todos na mesma grade de 10 Hz
    # Fixture de ~2 s a 60 fps: a duração do sinal bate com a do vídeo (dentro de um passo).
    duration = first.results["normalize"].data["probe"]["duration_s"]
    assert abs(next(iter(lengths)) * 0.1 - duration) <= 0.1 + 1e-6
    # O tom constante do jogo e o do microfone têm energia bem acima do piso.
    assert load_signal(metas["game.energy_db"]).values.mean() > -60
    assert load_signal(metas["mic.energy_db"]).values.mean() > -60


@needs_ffmpeg
def test_changing_a_dsp_parameter_invalidates_only_this_stage(
    db: Session, settings: Settings, fixture_folders: dict[str, Path]
) -> None:
    ingest_folder(db, fixture_folders["normal"], settings, AlwaysFreeGate())
    media = db.scalars(select(MediaFile)).one()
    run_pipeline(db, media, [*ingest_stages(), AudioSignalsStage()], settings, AlwaysFreeGate())

    changed = AudioSignalsStage(dsp.DspParams(baseline_s=120.0))
    report = run_pipeline(db, media, [*ingest_stages(), changed], settings, AlwaysFreeGate())
    assert report.executed == ["audio_signals"] and "audio" in report.cached
    assert db.scalars(select(Artifact).where(Artifact.stage == "audio_signals")).all().__len__() == 1


def test_missing_wav_is_a_clear_stage_error(settings: Settings, tmp_path: Path) -> None:
    ctx = StageContext(
        media_path=tmp_path / "m.mp4",
        out_dir=tmp_path,
        settings=settings,
        inputs={
            "audio": StageResult(data={"game": str(tmp_path / "nao.wav"), "mic": str(tmp_path / "x.wav")})
        },
    )
    with pytest.raises(StageError, match="rode a ingestão"):
        AudioSignalsStage().run(ctx)


def test_short_session_warns_about_baseline(settings: Settings, tmp_path: Path) -> None:
    import soundfile as sf

    for name in ("game", "mic"):
        sf.write(str(tmp_path / f"{name}.wav"), np.zeros(48000 * 3, dtype=np.float32), 48000)
    ctx = StageContext(
        media_path=tmp_path / "m.mp4",
        out_dir=tmp_path,
        settings=settings,
        inputs={
            "audio": StageResult(data={"game": str(tmp_path / "game.wav"), "mic": str(tmp_path / "mic.wav")})
        },
    )
    result = AudioSignalsStage().run(ctx)
    assert any("linha de base" in w for w in result.warnings)
    assert set(signal_metas(result)) == EXPECTED


def test_stage_params_are_in_the_cache_key() -> None:
    a = AudioSignalsStage().params(Settings(env="t", data_dir=Path("x")))
    b = AudioSignalsStage(dsp.DspParams(n_fft=2048)).params(Settings(env="t", data_dir=Path("x")))
    assert a != b
