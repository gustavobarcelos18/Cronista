"""Classificador de eventos sonoros: Audio Spectrogram Transformer treinado no AudioSet (527 classes, BSD-3).

Candidato do benchmark da 2C (PANNs, BEATs e CLAP são os outros). O AST dá um rótulo por janela de 10,24 s;
aqui a janela anda de `hop_s` em `hop_s` e vale só para o trecho central de `hop_s`, então os eventos têm a
resolução de `hop_s` (2,5 s). Serve para marcar onde há risada, grito, teclado, respiração ou explosão,
não para cortes precisos: os limites finos vêm do VAD e dos sinais.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import numpy as np

from cronista.audio.adapters.audio_io import MODEL_RATE, duration_s, package_version, read_segment
from cronista.audio.ports import Pause, SoundEventSpan

WINDOW_S = 10.24  # o AST espera 1024 quadros de 10 ms

# Rótulos do Cronista → classes do AudioSet (nomes exatos do `id2label` do modelo). A pontuação do rótulo é a
# maior entre as classes mapeadas.
LABEL_MAP: dict[str, tuple[str, ...]] = {
    "risada": ("Laughter", "Giggle", "Snicker", "Belly laugh", "Chuckle, chortle"),
    "grito": ("Screaming", "Shout", "Yell", "Whoop", "Bellow"),
    "teclado": ("Typing", "Computer keyboard", "Typewriter"),
    "respiracao": ("Breathing", "Gasp", "Pant", "Sigh"),
    "explosao": ("Explosion", "Boom", "Gunshot, gunfire"),
    "musica": ("Music",),
}


def merge_slices(
    scores: list[float], hop_s: float, offset_s: float, min_score: float
) -> list[tuple[float, float, float]]:
    """Fatias consecutivas com pontuação ≥ `min_score` viram um trecho: (início, fim, maior pontuação)."""
    spans: list[tuple[float, float, float]] = []
    run_start: int | None = None
    for i, score in enumerate([*scores, -1.0]):
        if score >= min_score:
            run_start = i if run_start is None else run_start
        elif run_start is not None:
            best = max(scores[run_start:i])
            spans.append((offset_s + run_start * hop_s, offset_s + i * hop_s, best))
            run_start = None
    return spans


class AstSoundClassifier:
    name = "ast-audioset"

    def __init__(
        self,
        download_root: Path,
        model_id: str = "MIT/ast-finetuned-audioset-10-10-0.4593",
        device: str = "cuda",
        hop_s: float = 2.5,
        block_s: float = 300.0,
        batch: int = 16,
        min_report: float = 0.1,
    ) -> None:
        self.version = package_version("transformers")
        self.options: dict[str, Any] = {
            "model_id": model_id,
            "device": device,
            "hop_s": hop_s,
            "block_s": block_s,
            "batch": batch,
            "min_report": min_report,
        }
        self._root = download_root
        self._extractor: Any = None
        self._model: Any = None
        self._columns: dict[str, list[int]] = {}

    def _load(self) -> None:
        if self._model is not None:
            return
        transformers: Any = importlib.import_module("transformers")
        torch: Any = importlib.import_module("torch")
        self._root.mkdir(parents=True, exist_ok=True)
        model_id, device = self.options["model_id"], self.options["device"]
        self._extractor = transformers.ASTFeatureExtractor.from_pretrained(
            model_id, cache_dir=str(self._root)
        )
        model = transformers.ASTForAudioClassification.from_pretrained(model_id, cache_dir=str(self._root))
        model = model.eval().to(device)
        self._model = model.half() if device == "cuda" else model
        names = {v: int(k) for k, v in model.config.id2label.items()}
        missing = [c for classes in LABEL_MAP.values() for c in classes if c not in names]
        if missing:
            raise RuntimeError(f"classes do AudioSet ausentes no modelo: {missing}")
        self._columns = {label: [names[c] for c in classes] for label, classes in LABEL_MAP.items()}
        self._torch = torch

    def _scores(self, windows: list[Any]) -> Any:
        """Pontuação por rótulo do Cronista para cada janela: matriz (janelas, rótulos)."""
        torch = self._torch
        device = self.options["device"]
        features = self._extractor(windows, sampling_rate=MODEL_RATE, return_tensors="pt")["input_values"]
        features = features.to(device)
        if device == "cuda":
            features = features.half()
        with torch.no_grad():
            probs = torch.sigmoid(self._model(features).logits.float()).cpu().numpy()
        return np.stack([probs[:, cols].max(axis=1) for cols in self._columns.values()], axis=1)

    def classify(self, wav: Path, *, pause: Pause) -> list[SoundEventSpan]:
        self._load()
        opts = self.options
        hop, block = float(opts["hop_s"]), float(opts["block_s"])
        labels = list(self._columns)
        total = duration_s(wav)
        per_label: dict[str, list[float]] = {label: [] for label in labels}
        centers = np.arange(0.0, total, hop)
        per_block = max(int(block / hop), 1)
        for first in range(0, len(centers), per_block):
            pause()
            group = centers[first : first + per_block]
            # Uma leitura por bloco, com o contexto da janela dos dois lados.
            lo = float(group[0]) - WINDOW_S / 2
            audio = read_segment(wav, lo, float(group[-1]) + WINDOW_S / 2)
            win = int(WINDOW_S * MODEL_RATE)
            windows = []
            for c in group:
                begin = round((float(c) - WINDOW_S / 2 - lo) * MODEL_RATE)
                windows.append(audio[begin : begin + win])
            for i in range(0, len(windows), int(opts["batch"])):
                matrix = self._scores(windows[i : i + int(opts["batch"])])
                for j, label in enumerate(labels):
                    per_label[label].extend(float(v) for v in matrix[:, j])
        events: list[SoundEventSpan] = []
        for label, scores in per_label.items():
            # A fatia de cada janela é centrada no seu instante: vai de c - hop/2 a c + hop/2.
            for start, end, best in merge_slices(scores, hop, -hop / 2, float(opts["min_report"])):
                events.append(
                    SoundEventSpan(
                        label=label, start_s=max(start, 0.0), end_s=min(end, total), score=min(best, 1.0)
                    )
                )
        return sorted(events, key=lambda e: (e.start_s, e.label))
