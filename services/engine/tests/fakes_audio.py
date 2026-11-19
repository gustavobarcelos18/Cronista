"""Modelos falsos e determinísticos para testar as portas de áudio sem GPU nem download."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from cronista.audio.ports import SoundEventSpan, SpeechSpan, Utterance, Word
from cronista.domain.types import Pause


class FakeDetector:
    name = "fake-vad"
    version = "1"

    def __init__(self, spans: Sequence[tuple[float, float]] = ((1.0, 2.5),)) -> None:
        self.spans = [SpeechSpan(start_s=a, end_s=b) for a, b in spans]
        self.options: dict[str, Any] = {}
        self.calls = 0

    def detect(self, wav: Path, *, pause: Pause) -> list[SpeechSpan]:
        self.calls += 1
        pause()
        return list(self.spans)


class FakeTranscriber:
    name = "fake-asr"
    version = "1"

    def __init__(self, text: str = "oi pessoal") -> None:
        self.text = text
        self.options: dict[str, Any] = {}
        self.calls = 0

    def transcribe(self, wav: Path, spans: Sequence[SpeechSpan], *, pause: Pause) -> list[Utterance]:
        self.calls += 1
        pause()
        out: list[Utterance] = []
        for span in spans:
            words = self.text.split()
            step = (span.end_s - span.start_s) / max(len(words), 1)
            out.append(
                Utterance(
                    text=self.text,
                    start_s=span.start_s,
                    end_s=span.end_s,
                    words=[
                        Word(text=w, start_s=span.start_s + i * step, end_s=span.start_s + (i + 1) * step)
                        for i, w in enumerate(words)
                    ],
                    confidence=0.9,
                )
            )
        return out


class FakeClassifier:
    name = "fake-sed"
    version = "1"

    def __init__(self, found: Sequence[SoundEventSpan] = ()) -> None:
        self.found = list(found)
        self.options: dict[str, Any] = {}
        self.calls = 0

    def classify(self, wav: Path, *, pause: Pause) -> list[SoundEventSpan]:
        self.calls += 1
        pause()
        return list(self.found)
