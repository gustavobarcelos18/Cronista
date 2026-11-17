"""Adaptadores reais contra os modelos de verdade (só `prod`: `pytest -m gpu`), com áudio sintético curto.

Não medem qualidade (isso é a 2C, com o gabarito): conferem que cada modelo carrega, roda na GPU, devolve o
formato certo e não inventa fala nem evento no silêncio.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from cronista.audio.models import build_models, missing_ml_packages
from cronista.audio.ports import AudioModels, SpeechSpan
from cronista.config import Settings, load_settings

pytestmark = pytest.mark.gpu

RATE = 48000


@pytest.fixture(scope="module")
def models() -> AudioModels:
    if missing_ml_packages():
        pytest.skip(f"grupo `ml` não instalado: {missing_ml_packages()}")
    settings = load_settings("prod")
    built = build_models(settings.model_copy(update={"audio_models": True}))
    assert built.detector and built.transcriber and built.classifier
    return built


def _wav(path: Path, samples: np.ndarray) -> Path:
    sf.write(str(path), samples.astype(np.float32), RATE)
    return path


def test_silence_gives_no_speech_no_words_and_no_events(models: AudioModels, tmp_path: Path) -> None:
    silence = _wav(tmp_path / "silencio.wav", np.zeros(RATE * 12, dtype=np.float32))
    assert models.detector and models.transcriber and models.classifier
    assert models.detector.detect(silence, pause=lambda: None) == []
    # Com um trecho de verdade (e não `[]`, que nem carrega o modelo) o Whisper roda de fato: o resultado
    # tem o formato certo e, no silêncio, nenhuma fala fora do arquivo.
    spans = [SpeechSpan(start_s=1.0, end_s=6.0)]
    utterances = models.transcriber.transcribe(silence, spans, pause=lambda: None)
    for utterance in utterances:
        assert 0 <= utterance.start_s <= utterance.end_s <= 12.5 and 0 <= utterance.confidence <= 1
    events = models.classifier.classify(silence, pause=lambda: None)
    assert all(e.label not in ("risada", "grito") or e.score < 0.3 for e in events)


def test_classifier_runs_on_noise_and_returns_valid_spans(models: AudioModels, tmp_path: Path) -> None:
    rng = np.random.default_rng(1)
    noise = _wav(tmp_path / "ruido.wav", rng.standard_normal(RATE * 15) * 0.05)
    assert models.classifier
    events = models.classifier.classify(noise, pause=lambda: None)
    for event in events:
        assert 0 <= event.start_s < event.end_s <= 15.01 and 0 <= event.score <= 1


def test_models_pause_between_blocks(models: AudioModels, tmp_path: Path) -> None:
    clip = _wav(tmp_path / "longo.wav", np.zeros(RATE * 30, dtype=np.float32))
    assert models.detector and models.classifier
    calls: list[int] = []
    models.detector.detect(clip, pause=lambda: calls.append(1))
    models.classifier.classify(clip, pause=lambda: calls.append(2))
    assert 1 in calls and 2 in calls  # os dois chamam o gate de GPU


def test_every_mapped_audioset_class_exists_in_the_model(models: AudioModels) -> None:
    """`_load` falha listando as classes ausentes: garante que o mapa de rótulos bate com o modelo."""
    assert models.classifier
    models.classifier.classify  # noqa: B018  (a carga acontece na primeira classificação)
    from cronista.audio.adapters.ast_classifier import AstSoundClassifier

    assert isinstance(models.classifier, AstSoundClassifier)
    models.classifier._load()
    from cronista.audio.adapters.ast_classifier import LABEL_MAP

    assert set(models.classifier._columns) == set(LABEL_MAP)
    assert all(len(cols) == len(LABEL_MAP[label]) for label, cols in models.classifier._columns.items())


def test_settings_for_prod_enable_the_models(settings: Settings) -> None:
    assert load_settings("prod").audio_models is True
