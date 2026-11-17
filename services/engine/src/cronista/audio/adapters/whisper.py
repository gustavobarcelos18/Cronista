"""Transcrição com faster-whisper (CTranslate2), só nos trechos de fala que o VAD achou."""

from __future__ import annotations

import importlib
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from cronista.audio.adapters.audio_io import package_version, read_segment
from cronista.audio.ports import Pause, SpeechSpan, Utterance, Word

NO_SPEECH_PROB = 0.6
LOW_LOGPROB = -1.0


def chunk_spans(
    spans: Sequence[SpeechSpan], merge_gap_s: float, max_chunk_s: float
) -> list[tuple[float, float]]:
    """Agrupa trechos de fala próximos em janelas de até `max_chunk_s` (o Whisper trabalha em 30 s).

    Trechos curtos e vizinhos viram uma chamada só, em vez de milhares de chamadas minúsculas; um trecho que
    sozinho passa do limite fica como está (o faster-whisper o divide por conta própria).
    """
    chunks: list[tuple[float, float]] = []
    for span in sorted(spans, key=lambda s: s.start_s):
        if chunks:
            start, end = chunks[-1]
            if span.start_s - end <= merge_gap_s and span.end_s - start <= max_chunk_s:
                chunks[-1] = (start, max(end, span.end_s))
                continue
        chunks.append((span.start_s, span.end_s))
    return chunks


class FasterWhisperTranscriber:
    def __init__(
        self,
        download_root: Path,
        model: str = "large-v3-turbo",
        compute_type: str = "int8_float16",
        language: str = "pt",
        device: str = "cuda",
        beam_size: int = 5,
        merge_gap_s: float = 1.5,
        max_chunk_s: float = 30.0,
        pad_s: float = 0.2,
    ) -> None:
        self.name = f"faster-whisper-{model}"
        self.version = package_version("faster-whisper")
        self.options: dict[str, Any] = {
            "compute_type": compute_type,
            "language": language,
            "device": device,
            "beam_size": beam_size,
            "merge_gap_s": merge_gap_s,
            "max_chunk_s": max_chunk_s,
            "pad_s": pad_s,
        }
        self._model_name, self._root = model, download_root
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            module: Any = importlib.import_module("faster_whisper")
            self._root.mkdir(parents=True, exist_ok=True)
            self._model = module.WhisperModel(
                self._model_name,
                device=self.options["device"],
                compute_type=self.options["compute_type"],
                download_root=str(self._root),
            )
        return self._model

    def transcribe(self, wav: Path, spans: Sequence[SpeechSpan], *, pause: Pause) -> list[Utterance]:
        model = self._load()
        opts = self.options
        out: list[Utterance] = []
        for start, end in chunk_spans(spans, opts["merge_gap_s"], opts["max_chunk_s"]):
            pause()
            lead = max(start - opts["pad_s"], 0.0)
            audio = read_segment(wav, lead, end + opts["pad_s"])
            segments, _info = model.transcribe(
                audio,
                language=opts["language"],
                beam_size=opts["beam_size"],
                word_timestamps=True,
                vad_filter=False,  # o VAD já cortou os trechos; não filtrar duas vezes
                condition_on_previous_text=False,  # evita repetição em cadeia (alucinação)
            )
            for seg in segments:
                text = str(seg.text).strip()
                if not text or (seg.no_speech_prob > NO_SPEECH_PROB and seg.avg_logprob < LOW_LOGPROB):
                    continue  # silêncio ou ruído que o modelo "transcreveu" sem acreditar no que ouviu
                words = [
                    Word(
                        text=str(w.word).strip(),
                        start_s=lead + float(w.start),
                        end_s=lead + float(w.end),
                        probability=min(max(float(w.probability), 0.0), 1.0),
                    )
                    for w in (seg.words or [])
                ]
                out.append(
                    Utterance(
                        text=text,
                        start_s=lead + float(seg.start),
                        end_s=lead + max(float(seg.end), float(seg.start)),
                        words=words,
                        confidence=min(max(math.exp(float(seg.avg_logprob)), 0.0), 1.0),
                    )
                )
        return out
