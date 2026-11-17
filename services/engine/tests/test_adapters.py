"""Adaptadores reais, na parte que não precisa de modelo baixado: agrupamento, fusão, leitura e seleção."""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from cronista.audio.adapters.ast_classifier import LABEL_MAP, merge_slices
from cronista.audio.adapters.audio_io import MODEL_RATE, duration_s, iter_blocks, read_segment
from cronista.audio.adapters.whisper import chunk_spans
from cronista.audio.models import build_models, missing_ml_packages
from cronista.audio.ports import SpeechSpan
from cronista.config import Settings

needs_torchaudio = pytest.mark.skipif(find_spec("torchaudio") is None, reason="grupo `ml` não instalado")


def spans(*pairs: tuple[float, float]) -> list[SpeechSpan]:
    return [SpeechSpan(start_s=a, end_s=b) for a, b in pairs]


def test_chunk_spans_merges_close_speech_up_to_the_window() -> None:
    assert chunk_spans(spans((0, 2), (3, 5), (6, 8)), merge_gap_s=1.5, max_chunk_s=30) == [(0, 8)]
    assert chunk_spans(spans((0, 2), (10, 12)), merge_gap_s=1.5, max_chunk_s=30) == [(0, 2), (10, 12)]
    # Passaria de 30 s: abre outro grupo mesmo com a pausa curta.
    assert chunk_spans(spans((0, 20), (21, 35)), merge_gap_s=1.5, max_chunk_s=30) == [(0, 20), (21, 35)]
    # Um trecho sozinho maior que o limite fica inteiro; a entrada fora de ordem é ordenada.
    assert chunk_spans(spans((50, 90), (0, 1)), merge_gap_s=1.5, max_chunk_s=30) == [(0, 1), (50, 90)]
    assert chunk_spans([], merge_gap_s=1.5, max_chunk_s=30) == []


def test_merge_slices_turns_runs_above_the_threshold_into_spans() -> None:
    scores = [0.0, 0.4, 0.9, 0.5, 0.0, 0.0, 0.3, 0.0]
    found = merge_slices(scores, hop_s=2.5, offset_s=-1.25, min_score=0.3)
    assert found == [(-1.25 + 1 * 2.5, -1.25 + 4 * 2.5, 0.9), (-1.25 + 6 * 2.5, -1.25 + 7 * 2.5, 0.3)]
    assert merge_slices([0.1, 0.2], 2.5, 0.0, 0.3) == []
    assert merge_slices([0.5, 0.6], 2.5, 0.0, 0.3) == [(0.0, 5.0, 0.6)]  # corrida até o fim da lista


def test_every_cronista_label_has_audioset_classes() -> None:
    assert {"risada", "grito", "teclado", "respiracao"} <= set(LABEL_MAP)
    assert all(classes for classes in LABEL_MAP.values())


def test_models_are_off_by_default_and_without_the_ml_group(settings: Settings) -> None:
    assert build_models(settings).detector is None  # audio_models=False: dev só usa os sinais de CPU
    enabled = settings.model_copy(update={"audio_models": True})
    if missing_ml_packages():
        assert build_models(enabled).detector is None  # sem o grupo `ml` instalado, o mesmo
    else:
        built = build_models(enabled)
        assert built.detector and built.transcriber and built.classifier
        assert built.transcriber.name == "faster-whisper-large-v3-turbo"
        assert built.transcriber.options["language"] == "pt"


def test_models_dir_defaults_to_data_models(settings: Settings, tmp_path: Path) -> None:
    assert settings.models_path == settings.data_dir / "models"
    assert settings.model_copy(update={"models_dir": tmp_path}).models_path == tmp_path


def _wav(path: Path, seconds: float, rate: int) -> Path:
    t = np.arange(int(seconds * rate)) / rate
    sf.write(str(path), (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), rate)
    return path


@needs_torchaudio
def test_read_segment_resamples_to_16k_and_pads_outside_the_file(tmp_path: Path) -> None:
    wav = _wav(tmp_path / "a.wav", 4.0, 48000)
    assert duration_s(wav) == pytest.approx(4.0)
    middle = read_segment(wav, 1.0, 2.0)
    assert middle.dtype == np.float32 and len(middle) == MODEL_RATE and np.abs(middle).max() > 0.4
    padded = read_segment(wav, -1.0, 1.0)  # 1 s antes do arquivo = silêncio
    assert len(padded) == 2 * MODEL_RATE and np.abs(padded[:MODEL_RATE]).max() < 0.01
    assert np.abs(padded[MODEL_RATE:]).max() > 0.4
    tail = read_segment(wav, 3.5, 5.0)  # passa do fim
    assert len(tail) == round(1.5 * MODEL_RATE) and np.abs(tail[-MODEL_RATE // 2 :]).max() < 0.01


@needs_torchaudio
def test_iter_blocks_cover_the_whole_file_in_order(tmp_path: Path) -> None:
    wav = _wav(tmp_path / "b.wav", 5.5, 16000)
    blocks = list(iter_blocks(wav, 2.0))
    assert [round(start, 1) for start, _ in blocks] == [0.0, 2.0, 4.0]
    assert sum(len(audio) for _, audio in blocks) == round(5.5 * MODEL_RATE)
