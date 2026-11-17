"""Embeddings de imagem e texto em espaço compartilhado: SigLIP, SigLIP 2 e CLIP (transformers, grupo `ml`).

Os três têm a mesma interface do `transformers` (`get_image_features` / `get_text_features`); mudam só a
normalização dos pixels e o tratamento do texto. O modelo só é baixado na primeira etapa que o usa, e só se
`video_embedder` estiver definido na configuração (ou o `bench-video` pedir). Escolha final: histórico §48.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from cronista.audio.adapters.audio_io import package_version
from cronista.video.ports import Embeddings, Pause, RgbFrames


def input_size_for(model_id: str) -> int:
    """Lado do quadro quadrado pelo nome do checkpoint (`...-384` → 384); 224 se o nome não diz."""
    match = re.search(r"-(\d{3})$", model_id)
    return int(match.group(1)) if match else 224


class SiglipEmbedder:
    name = "siglip"
    mean = (0.5, 0.5, 0.5)
    std = (0.5, 0.5, 0.5)
    lowercase_text = True
    text_padding: dict[str, Any] = {"padding": "max_length", "max_length": 64}  # noqa: RUF012

    def __init__(
        self,
        download_root: Path,
        model_id: str = "google/siglip-base-patch16-224",
        device: str = "cuda",
        batch: int = 64,
    ) -> None:
        self.version = package_version("transformers")
        self.options: dict[str, Any] = {"model_id": model_id, "device": device, "batch": batch}
        self.input_size = input_size_for(model_id)
        self.dim = 0  # só se sabe depois do primeiro lote
        self._root = download_root
        self._model: Any = None
        self._transformers: Any = None
        self._tokenizer: Any = None
        self._torch: Any = None

    def _load(self) -> None:
        if self._model is not None:
            return
        transformers: Any = importlib.import_module("transformers")
        torch: Any = importlib.import_module("torch")
        self._root.mkdir(parents=True, exist_ok=True)
        model_id, device = self.options["model_id"], self.options["device"]
        model = transformers.AutoModel.from_pretrained(model_id, cache_dir=str(self._root)).eval().to(device)
        self._transformers, self._torch = transformers, torch
        self._model = model.half() if device == "cuda" else model

    def _normalized(self, tensor: Any) -> Embeddings:
        out = getattr(tensor, "pooler_output", tensor).float()  # transformers 5 devolve um objeto de saída
        out = out / out.norm(dim=-1, keepdim=True).clamp(min=1e-6)
        return np.asarray(out.cpu().numpy(), dtype=np.float32)

    def embed_images(self, frames: RgbFrames, *, pause: Pause) -> Embeddings:
        self._load()
        torch, device, step = self._torch, self.options["device"], int(self.options["batch"])
        mean = torch.tensor(self.mean, device=device).view(1, 3, 1, 1)
        std = torch.tensor(self.std, device=device).view(1, 3, 1, 1)
        parts: list[Embeddings] = []
        for i in range(0, len(frames), step):
            pause()
            # Os quadros já chegam no tamanho do modelo; sem Pillow/torchvision a normalização é feita aqui.
            batch = torch.from_numpy(np.ascontiguousarray(frames[i : i + step])).to(device)
            pixels = (batch.permute(0, 3, 1, 2).float() / 255.0 - mean) / std
            if device == "cuda":
                pixels = pixels.half()
            with torch.no_grad():
                parts.append(self._normalized(self._model.get_image_features(pixel_values=pixels)))
        out = np.concatenate(parts) if parts else np.zeros((0, self.dim), np.float32)
        if len(out):
            self.dim = int(out.shape[1])
        return out

    def embed_text(self, texts: Sequence[str]) -> Embeddings:
        self._load()
        torch, device = self._torch, self.options["device"]
        if self._tokenizer is None:  # SigLIP precisa de `sentencepiece`; só a busca por texto usa
            self._tokenizer = self._transformers.AutoTokenizer.from_pretrained(
                self.options["model_id"], cache_dir=str(self._root)
            )
        items = [t.lower() for t in texts] if self.lowercase_text else list(texts)
        tokens = self._tokenizer(items, return_tensors="pt", **self.text_padding)["input_ids"].to(device)
        with torch.no_grad():
            return self._normalized(self._model.get_text_features(input_ids=tokens))


class Siglip2Embedder(SiglipEmbedder):
    name = "siglip2"


class ClipEmbedder(SiglipEmbedder):
    name = "clip"
    mean = (0.48145466, 0.4578275, 0.40821073)
    std = (0.26862954, 0.26130258, 0.27577711)
    lowercase_text = False
    text_padding: dict[str, Any] = {"padding": True, "truncation": True, "max_length": 77}  # noqa: RUF012
