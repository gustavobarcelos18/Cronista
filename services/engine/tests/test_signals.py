"""Sinais numéricos em CPU, sobre áudio sintético (sem FFmpeg): grade em quadros, novidade, periodicidade."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from cronista.audio import dsp
from cronista.audio.signals import (
    frame_to_index,
    index_to_frame,
    load_signal,
    signal_metas,
    write_signal,
)
from cronista.domain.models import StageResult

RATE = 48000
PARAMS = dsp.DspParams()


def write_wav(path: Path, samples: np.ndarray, rate: int = RATE) -> Path:
    sf.write(str(path), samples.astype(np.float32), rate, subtype="PCM_16")
    return path


def noise(seconds: float, level_db: float, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(int(seconds * RATE)) * 10 ** (level_db / 20)).astype(np.float32)


def click_train(
    seconds: float, period_s: float, *, level_db: float = -30, noise_db: float = -60
) -> np.ndarray:
    """Impactos regulares (passos, mineração) sobre ruído baixo."""
    out = noise(seconds, noise_db)
    burst = np.random.default_rng(3).standard_normal(480) * np.hanning(480)  # banda larga, como um passo
    click = (burst * 10 ** (level_db / 20)).astype(np.float32)
    for t in np.arange(0.5, seconds - 0.5, period_s):
        start = int(t * RATE)
        out[start : start + len(click)] += click
    return out


def test_frame_index_grid_is_exact_integer_math() -> None:
    assert [frame_to_index(f, 6) for f in (0, 5, 6, 11, 12)] == [0, 0, 1, 1, 2]
    assert index_to_frame(10, 6) == 60
    assert dsp.hop_samples(48000, 6) == 4800 and dsp.hop_samples(44100, 6) == 4410
    with pytest.raises(ValueError, match="divide a grade"):
        dsp.hop_samples(22050, 7)


def test_signal_roundtrip_and_slicing(tmp_path: Path) -> None:
    meta = write_signal(
        tmp_path, "teste", np.arange(10), unit="u", source_track="game", version="1", params={"a": 1}
    )
    sig = load_signal(meta)
    assert sig.values.dtype == np.float32 and meta.length == 10 and sig.end_frame == 60
    assert sig.slice(0, 12).tolist() == [0, 1]  # quadros 0..11 = amostras 0 e 1
    assert sig.slice(7, 8).tolist() == [1]  # um quadro dentro da amostra 1
    assert sig.slice(6, 7).tolist() == [1]
    assert sig.slice(58, 600).tolist() == [9]  # fora do fim: só o que existe
    assert sig.slice(30, 30).size == 0 and sig.slice(1000, 2000).size == 0
    assert sig.at_frame(13) == 2.0
    with pytest.raises(IndexError):
        sig.at_frame(60)


def test_signal_must_be_one_dimensional(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unidimensional"):
        write_signal(tmp_path, "x", np.zeros((2, 2)), unit="u", source_track="game", version="1", params={})


def test_signal_metas_reads_the_stage_result(tmp_path: Path) -> None:
    meta = write_signal(tmp_path, "a", [1, 2], unit="u", source_track="mic", version="1", params={})
    result = StageResult(data={"signals": {"a": meta.model_dump()}})
    assert signal_metas(result)["a"].length == 2 and signal_metas(StageResult()) == {}


def test_energy_and_length_follow_the_hop_grid(tmp_path: Path) -> None:
    quiet = noise(5.0, -60)
    loud = noise(5.0, -20, seed=2)
    path = write_wav(tmp_path / "a.wav", np.concatenate([quiet, loud]))
    base = dsp.analyze_track(path, PARAMS, with_onset=True)
    assert len(base.energy_db) == 100 == len(base.onset)  # 10 s a 10 Hz
    assert base.energy_db[:50].mean() == pytest.approx(-60, abs=1.0)
    assert base.energy_db[50:].mean() == pytest.approx(-20, abs=1.0)


def test_partial_last_hop_is_kept(tmp_path: Path) -> None:
    path = write_wav(tmp_path / "a.wav", noise(1.05, -40))  # 10,5 passos
    assert len(dsp.analyze_track(path, PARAMS, with_onset=True).energy_db) == 11


def test_blocks_do_not_change_the_result(tmp_path: Path) -> None:
    path = write_wav(tmp_path / "a.wav", click_train(20, 1.0))
    whole = dsp.analyze_track(path, dsp.DspParams(block_s=60.0), with_onset=True)
    split = dsp.analyze_track(
        path, dsp.DspParams(block_s=3.7), with_onset=True
    )  # bloco não alinhado ao passo
    np.testing.assert_allclose(whole.energy_db, split.energy_db, atol=1e-3)
    np.testing.assert_allclose(whole.onset, split.onset, atol=1e-3)


def test_between_blocks_is_called_so_the_gpu_gate_can_pause(tmp_path: Path) -> None:
    path = write_wav(tmp_path / "a.wav", noise(10, -40))
    calls: list[int] = []
    dsp.analyze_track(
        path, dsp.DspParams(block_s=2.0), with_onset=False, between_blocks=lambda: calls.append(1)
    )
    assert len(calls) == 5


def test_silence_has_no_novelty_and_no_periodicity(tmp_path: Path) -> None:
    path = write_wav(tmp_path / "s.wav", np.zeros(RATE * 60, dtype=np.float32))
    base = dsp.analyze_track(path, PARAMS, with_onset=True)
    assert base.energy_db.max() == pytest.approx(dsp.DB_FLOOR)
    assert dsp.novelty(base.onset, PARAMS).max() == 0.0
    assert dsp.periodicity(base.onset, PARAMS).max() == 0.0


def test_explosion_in_steady_noise_spikes_novelty_but_is_not_periodic(tmp_path: Path) -> None:
    audio = noise(120, -50)
    boom = np.random.default_rng(7).standard_normal(RATE // 2) * 10 ** (-8 / 20) * np.hanning(RATE // 2)
    audio[60 * RATE : 60 * RATE + len(boom)] += boom.astype(np.float32)  # aos 60 s
    base = dsp.analyze_track(write_wav(tmp_path / "b.wav", audio), PARAMS, with_onset=True)
    nov = dsp.novelty(base.onset, PARAMS)
    assert nov[598:606].max() > 10  # pico na explosão
    assert np.median(nov) < 1.0 and np.percentile(nov[:500], 99) < 5  # fora dela, perto de zero
    per = dsp.periodicity(base.onset, PARAMS)
    assert per.max() < 0.5


def test_regular_clicks_are_periodic_with_low_novelty(tmp_path: Path) -> None:
    base = dsp.analyze_track(write_wav(tmp_path / "c.wav", click_train(120, 0.8)), PARAMS, with_onset=True)
    per = dsp.periodicity(base.onset, PARAMS)
    nov = dsp.novelty(base.onset, PARAMS)
    assert np.median(per[100:-100]) > 0.6
    assert np.median(nov) < 2.0


def test_periodic_beats_noise_floor_by_a_wide_margin(tmp_path: Path) -> None:
    clicks = dsp.analyze_track(write_wav(tmp_path / "c.wav", click_train(120, 0.8)), PARAMS, with_onset=True)
    steady = dsp.analyze_track(write_wav(tmp_path / "n.wav", noise(120, -50)), PARAMS, with_onset=True)
    assert np.median(dsp.periodicity(clicks.onset, PARAMS)) > 2 * np.median(
        dsp.periodicity(steady.onset, PARAMS)
    )


def test_short_signal_does_not_crash(tmp_path: Path) -> None:
    base = dsp.analyze_track(write_wav(tmp_path / "t.wav", noise(2, -40)), PARAMS, with_onset=True)
    assert len(dsp.novelty(base.onset, PARAMS)) == len(base.onset) == 20
    assert len(dsp.periodicity(base.onset, PARAMS)) == 20
    empty = np.zeros(0, dtype=np.float32)
    assert len(dsp.novelty(empty, PARAMS)) == 0 and len(dsp.periodicity(empty, PARAMS)) == 0


def test_mic_energy_above_baseline_flags_a_sudden_shout() -> None:
    energy = np.full(2000, -50.0, dtype=np.float32)
    energy[1000:1010] = -15.0
    rel = dsp.energy_above_baseline(energy, PARAMS)
    assert rel[1005] == pytest.approx(35.0, abs=0.5) and abs(rel[100]) < 0.5


def test_rf64_wav_is_read_in_blocks(tmp_path: Path) -> None:
    path = tmp_path / "grande.wav"
    sf.write(str(path), noise(3, -40), RATE, subtype="PCM_16", format="RF64")
    with sf.SoundFile(str(path)) as handle:
        assert handle.format == "RF64"
    base = dsp.analyze_track(path, dsp.DspParams(block_s=1.0), with_onset=True)
    assert len(base.energy_db) == 30


def test_hop_frames_must_divide_the_60fps_grid() -> None:
    assert dsp.DspParams(hop_frames=10).per_second == 6 and dsp.DspParams().per_second == 10
    for bad in (0, -6, 7, 8):
        with pytest.raises(ValueError, match="precisa dividir"):
            dsp.DspParams(hop_frames=bad)


def test_windows_follow_the_grid_for_a_non_default_hop(tmp_path: Path) -> None:
    """Com hop de 12 quadros (5 amostras/s) a janela de 300 s tem 1500 amostras, não um valor arredondado."""
    params = dsp.DspParams(hop_frames=12)
    base = dsp.analyze_track(write_wav(tmp_path / "h.wav", click_train(60, 0.8)), params, with_onset=True)
    assert len(base.energy_db) == 300  # 60 s a 5 Hz
    assert len(dsp.novelty(base.onset, params)) == 300


def test_periodicity_chunks_give_the_same_result(tmp_path: Path) -> None:
    base = dsp.analyze_track(write_wav(tmp_path / "c.wav", click_train(90, 0.8)), PARAMS, with_onset=True)
    np.testing.assert_allclose(
        dsp.periodicity(base.onset, PARAMS, chunk=7), dsp.periodicity(base.onset, PARAMS), atol=1e-6
    )
