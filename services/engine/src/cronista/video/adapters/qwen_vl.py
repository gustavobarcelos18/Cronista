"""Qwen3-VL local pelo `transformers` (sem Ollama), grupo `ml`/`bench`, GPU. Escolha e números: histórico §49.

Nada é baixado ao importar nem ao construir: os pesos só vêm na primeira pergunta (`_load`), e só se
`vlm_model` estiver na configuração.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import numpy as np

from cronista.audio.adapters.audio_io import package_version
from cronista.video.ports import RgbImage


class QwenVL:
    name = "qwen-vl"

    def __init__(self, cache_dir: Path, model_id: str, quant4: bool = False) -> None:
        self.cache_dir = cache_dir
        self.model_id = model_id
        self.options: dict[str, Any] = {"model": model_id, "quant4": quant4}
        self._quant4 = quant4
        self._loaded: tuple[Any, Any, Any] | None = None

    @property
    def version(self) -> str:
        return package_version("transformers")

    def _load(self) -> tuple[Any, Any, Any]:
        if self._loaded is None:
            transformers: Any = importlib.import_module("transformers")
            torch: Any = importlib.import_module("torch")
            cache = str(self.cache_dir)
            kwargs: dict[str, Any] = {"device_map": {"": 0}, "cache_dir": cache}
            if self._quant4:
                kwargs["quantization_config"] = transformers.BitsAndBytesConfig(
                    load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_quant_type="nf4"
                )
            else:
                kwargs["dtype"] = torch.bfloat16
            processor = transformers.AutoProcessor.from_pretrained(self.model_id, cache_dir=cache)
            auto = transformers.AutoModelForImageTextToText
            self._loaded = (torch, processor, auto.from_pretrained(self.model_id, **kwargs).eval())
        return self._loaded

    def ask(self, image: RgbImage, prompt: str, max_new_tokens: int = 24) -> str:
        torch, processor, model = self._load()
        pil: Any = importlib.import_module("PIL.Image").fromarray(np.ascontiguousarray(image))
        messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}]
        text = processor.apply_chat_template(messages, add_generation_prompt=True)
        inputs = processor(text=[text], images=[pil], return_tensors="pt").to(model.device)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
        new = out[:, inputs["input_ids"].shape[1] :]
        return str(processor.batch_decode(new, skip_special_tokens=True)[0]).strip()
