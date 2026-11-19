"""Embedder falso e determinístico: cor média em grade 4x4 (48 dimensões), normalizada."""

from __future__ import annotations

import zlib
from collections.abc import Sequence
from typing import Any

import numpy as np

from cronista.domain.types import Pause
from cronista.video.ports import Embeddings, RgbFrames


class FakeEmbedder:
    name = "fake-cor"
    version = "1"

    def __init__(self) -> None:
        self.options: dict[str, Any] = {}

    dim = 48
    input_size = 32

    def embed_images(self, frames: RgbFrames, *, pause: Pause) -> Embeddings:
        pause()
        n, h, w, _ = frames.shape
        grid = frames.reshape(n, 4, h // 4, 4, w // 4, 3).mean(axis=(2, 4)).reshape(n, -1)
        norm = np.maximum(np.linalg.norm(grid, axis=1, keepdims=True), 1e-6)
        return (grid / norm).astype(np.float32)

    def embed_text(self, texts: Sequence[str]) -> Embeddings:
        out = np.stack([np.random.default_rng(zlib.crc32(t.encode())).normal(size=self.dim) for t in texts])
        return (out / np.linalg.norm(out, axis=1, keepdims=True)).astype(np.float32)
