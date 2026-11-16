"""Quais modelos de áudio existem nesta máquina.

Hoje nenhum: os adaptadores reais (Silero, faster-whisper, classificador de eventos) entram na 2B, em
`prod`, como dependências opcionais. Até lá `cronista analyze` roda só os sinais de CPU e diz o que
deixou de rodar.
"""

from __future__ import annotations

from cronista.audio.ports import AudioModels
from cronista.config import Settings


def build_models(settings: Settings) -> AudioModels:
    return AudioModels()
