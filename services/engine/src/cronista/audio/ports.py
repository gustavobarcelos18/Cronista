"""Portas dos modelos de áudio (VAD, transcrição, eventos sonoros).

As implementações reais (Silero, faster-whisper, PANNs/BEATs/CLAP) entram na 2B, no PC com GPU, sem
tocar no resto: o núcleo só conhece estes contratos. Os tempos saem em **segundos dentro do arquivo**
(é o que os modelos falam) e viram quadros inteiros a 60 fps na etapa, na borda (`domain.frames`).

Contrato comum: cada método recebe `pause`, que o adaptador chama **entre blocos** de trabalho. É o
gate de GPU: bloqueia enquanto o OBS grava ou há jogo em tela cheia (CLAUDE.md, "Ambientes").
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

Pause = Callable[[], None]

GAME_TRACK = "game"
MIC_TRACK = "mic"
MIC_EVENT_LABELS = frozenset({"risada", "grito"})
"""No microfone só estes rótulos viram evento: teclado e respiração são descartados (plano, seção 3)."""


class SpeechSpan(BaseModel):
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)


class Word(BaseModel):
    text: str
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    probability: float = Field(default=1.0, ge=0.0, le=1.0)


class Utterance(BaseModel):
    text: str
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    words: list[Word] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class SoundEventSpan(BaseModel):
    label: str  # rótulo do Cronista (já normalizado pelo adaptador): risada, grito, explosao, musica…
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    score: float = Field(ge=0.0, le=1.0)


class SpeechDetector(Protocol):
    name: str
    version: str
    options: dict[str, Any]
    """Hiperparâmetros que mudam o resultado (limiar, idioma, precisão): entram na chave de cache."""

    def detect(self, wav: Path, *, pause: Pause) -> list[SpeechSpan]:
        """Trechos com fala (VAD). Clique de teclado e respiração são não-fala e ficam de fora."""
        ...


class Transcriber(Protocol):
    name: str
    version: str
    options: dict[str, Any]
    """Hiperparâmetros que mudam o resultado (limiar, idioma, precisão): entram na chave de cache."""

    def transcribe(self, wav: Path, spans: Sequence[SpeechSpan], *, pause: Pause) -> list[Utterance]:
        """Transcreve só os trechos de fala, com tempo por palavra."""
        ...


class SoundEventClassifier(Protocol):
    name: str
    version: str
    options: dict[str, Any]
    """Hiperparâmetros que mudam o resultado (limiar, idioma, precisão): entram na chave de cache."""

    def classify(self, wav: Path, *, pause: Pause) -> list[SoundEventSpan]:
        """Eventos sonoros da faixa (rótulos do Cronista)."""
        ...


@dataclass(frozen=True)
class AudioModels:
    """Modelos disponíveis nesta máquina. Sem nenhum (`dev`, antes da 2B), só rodam os sinais de CPU."""

    detector: SpeechDetector | None = None
    transcriber: Transcriber | None = None
    classifier: SoundEventClassifier | None = None
