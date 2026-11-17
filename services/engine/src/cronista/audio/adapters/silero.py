"""VAD com o Silero (MIT): separa fala de não-fala no microfone. Roda em CPU: o modelo tem ~2 MB."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from cronista.audio.adapters.audio_io import MODEL_RATE, iter_blocks, package_version
from cronista.audio.ports import Pause, SpeechSpan


class SileroVad:
    name = "silero-vad"

    def __init__(
        self,
        threshold: float = 0.5,
        min_speech_ms: int = 250,
        min_silence_ms: int = 300,
        block_s: float = 300.0,
    ) -> None:
        self.version = package_version("silero-vad")
        self.options: dict[str, Any] = {
            "threshold": threshold,
            "min_speech_ms": min_speech_ms,
            "min_silence_ms": min_silence_ms,
            "block_s": block_s,
        }
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            self._model = importlib.import_module("silero_vad").load_silero_vad()
        return self._model

    def detect(self, wav: Path, *, pause: Pause) -> list[SpeechSpan]:
        silero: Any = importlib.import_module("silero_vad")
        torch: Any = importlib.import_module("torch")
        model = self._load()
        opts = self.options
        spans: list[SpeechSpan] = []
        for offset, audio in iter_blocks(wav, opts["block_s"]):
            pause()
            found = silero.get_speech_timestamps(
                torch.from_numpy(audio),
                model,
                sampling_rate=MODEL_RATE,
                threshold=opts["threshold"],
                min_speech_duration_ms=opts["min_speech_ms"],
                min_silence_duration_ms=opts["min_silence_ms"],
                return_seconds=False,  # em segundos o Silero arredonda a 0,1 s; em amostras o tempo é exato
            )
            for index, item in enumerate(found):
                start = offset + float(item["start"]) / MODEL_RATE
                end = offset + float(item["end"]) / MODEL_RATE
                last = spans[-1] if spans else None
                # Só a fala cortada na fronteira entre dois blocos (primeiro trecho do bloco) volta a ser um
                # trecho só; dentro do bloco, os cortes do Silero ficam como estão.
                if index == 0 and last is not None and start - last.end_s <= opts["min_silence_ms"] / 1000:
                    spans[-1] = SpeechSpan(start_s=last.start_s, end_s=max(end, last.end_s))
                else:
                    spans.append(SpeechSpan(start_s=start, end_s=end))
        return spans
