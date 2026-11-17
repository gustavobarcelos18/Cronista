"""Quais modelos de áudio existem nesta máquina.

Em `dev` (ou sem o grupo `ml` instalado) nenhum: `cronista analyze` roda só os sinais de CPU e diz o que
deixou de rodar. Em `prod`, com `audio_models: true` e `uv sync --group ml`, entram Silero (VAD),
faster-whisper e o classificador de eventos. Os modelos só são baixados e carregados na primeira vez
que uma etapa os usa.
"""

from __future__ import annotations

from importlib.util import find_spec

from cronista.audio.ports import AudioModels
from cronista.config import Settings

ML_PACKAGES = ("torch", "torchaudio", "faster_whisper", "silero_vad", "transformers")


def missing_ml_packages() -> list[str]:
    """Pacotes do grupo `ml` que não estão instalados (vazio = pronto para usar os modelos)."""
    return [name for name in ML_PACKAGES if find_spec(name) is None]


def build_models(settings: Settings) -> AudioModels:
    if not settings.audio_models or missing_ml_packages():
        return AudioModels()
    from cronista.audio.adapters.ast_classifier import AstSoundClassifier
    from cronista.audio.adapters.silero import SileroVad
    from cronista.audio.adapters.whisper import FasterWhisperTranscriber

    root = settings.models_path
    return AudioModels(
        detector=SileroVad(),
        transcriber=FasterWhisperTranscriber(
            root / "whisper",
            model=settings.whisper_model,
            compute_type=settings.whisper_compute_type,
            language=settings.audio_language,
        ),
        classifier=AstSoundClassifier(root / "ast", model_id=settings.sound_model),
        mic_classifier=AstSoundClassifier(
            root / "ast", model_id=settings.sound_model, hop_s=0.5, window_s=2.0, min_report=0.1
        ),
    )
