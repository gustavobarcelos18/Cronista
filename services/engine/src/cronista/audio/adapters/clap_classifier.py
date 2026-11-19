"""Eventos sonoros zero-shot com CLAP (áudio e texto no mesmo espaço; transformers, grupo `ml`).

Candidato do benchmark de áudio (histórico §48). Sem treino: cada rótulo do Cronista vira frases em inglês e a
pontuação é a probabilidade (softmax sobre todas as frases, positivas e de fundo) somada por rótulo. As frases
são ponto de partida, sem ajuste; o resultado depende delas. Janela anda de `hop_s` em `hop_s` como no AST.

⚠️ Escrito em `dev` e rodado só no benchmark; API do `transformers` 5 a conferir se mudar.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import numpy as np

from cronista.audio.adapters.ast_classifier import merge_slices
from cronista.audio.adapters.audio_io import MODEL_RATE, duration_s, package_version, read_segment
from cronista.audio.ports import SoundEventSpan
from cronista.domain.types import Pause

CLAP_RATE = 48000

POSITIVE: dict[str, tuple[str, ...]] = {
    "risada": ("a person laughing", "laughter", "someone giggling and laughing out loud"),
    "exclamacao": ("a person shouting excitedly", "a person screaming", "an excited yell"),
    "teclado": ("keyboard typing", "mouse clicking"),
    "respiracao": ("a person breathing", "heavy breathing"),
    "explosao": ("an explosion", "a loud bang"),
    "musica": ("music playing", "video game background music"),
}
BACKGROUND = ("a person talking calmly", "silence", "room noise", "video game sound effects")


class ClapClassifier:
    name = "clap"

    def __init__(
        self,
        download_root: Path,
        model_id: str = "laion/clap-htsat-unfused",
        device: str = "cuda",
        hop_s: float = 0.5,
        window_s: float = 2.0,
        block_s: float = 120.0,
        batch: int = 32,
        min_report: float = 0.1,
    ) -> None:
        self.version = package_version("transformers")
        self.options: dict[str, Any] = {
            "model_id": model_id,
            "device": device,
            "hop_s": hop_s,
            "window_s": window_s,
            "block_s": block_s,
            "batch": batch,
            "min_report": min_report,
        }
        self._root = download_root
        self._model: Any = None
        self._extractor: Any = None
        self._text: Any = None
        self._torch: Any = None
        self._labels = list(POSITIVE)

    def _load(self) -> None:
        if self._model is not None:
            return
        transformers: Any = importlib.import_module("transformers")
        torch: Any = importlib.import_module("torch")
        self._root.mkdir(parents=True, exist_ok=True)
        model_id, device = self.options["model_id"], self.options["device"]
        model = transformers.ClapModel.from_pretrained(model_id, cache_dir=str(self._root)).eval().to(device)
        tokenizer = transformers.AutoTokenizer.from_pretrained(model_id, cache_dir=str(self._root))
        self._extractor = transformers.ClapFeatureExtractor.from_pretrained(
            model_id, cache_dir=str(self._root)
        )
        prompts = [p for label in self._labels for p in POSITIVE[label]] + list(BACKGROUND)
        tokens = tokenizer(prompts, padding=True, return_tensors="pt").to(device)
        with torch.no_grad():
            text = self._features(model.get_text_features(**tokens))
        self._torch, self._model, self._text, self._prompts = torch, model, text, prompts

    @staticmethod
    def _features(out: Any) -> Any:
        tensor = getattr(out, "pooler_output", out).float()
        return tensor / tensor.norm(dim=-1, keepdim=True).clamp(min=1e-6)

    def _scores(self, windows: list[Any]) -> Any:
        """Pontuação por rótulo para cada janela: matriz (janelas, rótulos)."""
        torch, device = self._torch, self.options["device"]
        upsampled = [self._upsample(w) for w in windows]
        inputs = self._extractor(upsampled, sampling_rate=CLAP_RATE, return_tensors="pt").to(device)
        with torch.no_grad():
            audio = self._features(self._model.get_audio_features(**inputs))
            scale = self._model.logit_scale_a.exp().float()
            probs = torch.softmax(scale * audio @ self._text.T, dim=-1).cpu().numpy()
        columns, start = [], 0
        for label in self._labels:
            size = len(POSITIVE[label])
            columns.append(probs[:, start : start + size].sum(axis=1))
            start += size
        return np.stack(columns, axis=1)

    def _upsample(self, audio: Any) -> Any:
        torch, functional = self._torch, importlib.import_module("torchaudio.functional")
        out = functional.resample(torch.from_numpy(audio), MODEL_RATE, CLAP_RATE)
        return np.asarray(out.numpy(), dtype=np.float32)

    def classify(self, wav: Path, *, pause: Pause) -> list[SoundEventSpan]:
        self._load()
        opts = self.options
        hop, window, block = float(opts["hop_s"]), float(opts["window_s"]), float(opts["block_s"])
        total = duration_s(wav)
        per_label: dict[str, list[float]] = {label: [] for label in self._labels}
        centers = np.arange(0.0, total, hop)
        per_block = max(int(block / hop), 1)
        half = window / 2
        for first in range(0, len(centers), per_block):
            pause()
            group = centers[first : first + per_block]
            lo = float(group[0]) - half
            audio = read_segment(wav, lo, float(group[-1]) + half)
            size = int(window * MODEL_RATE)
            windows = []
            for c in group:
                begin = round((float(c) - half - lo) * MODEL_RATE)
                windows.append(audio[begin : begin + size])
            for i in range(0, len(windows), int(opts["batch"])):
                matrix = self._scores(windows[i : i + int(opts["batch"])])
                for j, label in enumerate(self._labels):
                    per_label[label].extend(float(v) for v in matrix[:, j])
        events: list[SoundEventSpan] = []
        for label, scores in per_label.items():
            for start, end, best in merge_slices(scores, hop, -hop / 2, float(opts["min_report"])):
                events.append(
                    SoundEventSpan(
                        label=label, start_s=max(start, 0.0), end_s=min(end, total), score=min(best, 1.0)
                    )
                )
        return sorted(events, key=lambda e: (e.start_s, e.label))
