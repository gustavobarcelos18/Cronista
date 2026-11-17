"""Embeddings de imagem e texto com SigLIP (transformers + PyTorch, grupo `ml`).

⚠️ Não verificado em hardware nem com o checkpoint baixado (escrito em `dev`, sem GPU): conferir a API do
`transformers` instalado, o checkpoint e a escolha SigLIP ou CLIP no benchmark da 3B (`bench-video`) antes de
fixar a versão no plano (seção 5.2). O modelo só é baixado na primeira etapa que o usa, e só se
`video_embedder` estiver definido na configuração.
"""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from cronista.audio.adapters.audio_io import package_version
from cronista.video.ports import Embeddings, Pause, RgbFrames


class SiglipEmbedder:
    name = "siglip"

    def __init__(
        self,
        download_root: Path,
        model_id: str = "google/siglip-base-patch16-224",
        device: str = "cuda",
        batch: int = 64,
    ) -> None:
        self.version = package_version("transformers")
        self.options: dict[str, Any] = {"model_id": model_id, "device": device, "batch": batch}
        self.input_size = 224  # os checkpoints `-224` esperam 224x224; outro tamanho pede ajuste aqui
        self.dim = 768 if "base" in model_id else 1152
        self._root = download_root
        self._model: Any = None
        self._processor: Any = None
        self._torch: Any = None

    def _load(self) -> None:
        if self._model is not None:
            return
        transformers: Any = importlib.import_module("transformers")
        torch: Any = importlib.import_module("torch")
        self._root.mkdir(parents=True, exist_ok=True)
        model_id, device = self.options["model_id"], self.options["device"]
        processor = transformers.AutoProcessor.from_pretrained(model_id, cache_dir=str(self._root))
        model = transformers.AutoModel.from_pretrained(model_id, cache_dir=str(self._root)).eval().to(device)
        self._processor, self._torch = processor, torch
        self._model = model.half() if device == "cuda" else model

    def _normalized(self, tensor: Any) -> Embeddings:
        out = tensor.float()
        out = out / out.norm(dim=-1, keepdim=True).clamp(min=1e-6)
        return np.asarray(out.cpu().numpy(), dtype=np.float32)

    def embed_images(self, frames: RgbFrames, *, pause: Pause) -> Embeddings:
        self._load()
        torch, device, step = self._torch, self.options["device"], int(self.options["batch"])
        parts: list[Embeddings] = []
        for i in range(0, len(frames), step):
            pause()
            pixels = self._processor(images=list(frames[i : i + step]), return_tensors="pt")["pixel_values"]
            pixels = pixels.to(device)
            if device == "cuda":
                pixels = pixels.half()
            with torch.no_grad():
                parts.append(self._normalized(self._model.get_image_features(pixel_values=pixels)))
        return np.concatenate(parts) if parts else np.zeros((0, self.dim), np.float32)

    def embed_text(self, texts: Sequence[str]) -> Embeddings:
        self._load()
        torch, device = self._torch, self.options["device"]
        # SigLIP foi treinado com texto em minúsculas e preenchido até 64 tokens.
        tokens = self._processor(
            text=[t.lower() for t in texts], padding="max_length", max_length=64, return_tensors="pt"
        )["input_ids"].to(device)
        with torch.no_grad():
            return self._normalized(self._model.get_text_features(input_ids=tokens))
