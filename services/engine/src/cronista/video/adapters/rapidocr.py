"""OCR do HUD com RapidOCR (ONNX, CPU). Grupo `bench`/`ml`; verificar a versão instalada (>= 3.10)."""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from typing import Any

import numpy as np

from cronista.audio.adapters.audio_io import package_version
from cronista.video.ports import RgbFrames


class RapidOcrReader:
    name = "rapidocr"

    def __init__(self) -> None:
        self.options: dict[str, Any] = {"backend": "onnxruntime-cpu"}
        self._engine: Any = None
        self._new_api = True

    @property
    def version(self) -> str:
        return package_version("rapidocr")

    def _load(self) -> Any:
        if self._engine is None:
            try:
                module: Any = importlib.import_module("rapidocr")
            except ImportError:
                module = importlib.import_module("rapidocr_onnxruntime")
                self._new_api = False
            self._engine = module.RapidOCR()
        return self._engine

    def read(self, crops: Sequence[RgbFrames]) -> list[str]:
        engine = self._load()
        out: list[str] = []
        for crop in crops:
            result = engine(np.ascontiguousarray(crop[:, :, ::-1]))  # RGB -> BGR
            if self._new_api:
                texts = getattr(result, "txts", None) or ()
            else:
                texts = [line[1] for line in (result[0] or [])]
            out.append(" ".join(str(t) for t in texts).strip())
        return out
