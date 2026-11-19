"""Sinais em série temporal (lacuna técnica 4, plano da Fase 2).

Decisão: um sinal é um array `float32` em `.npy` no cache do SSD, referenciado pelo `result.json` da etapa
que o produziu. O banco não guarda amostras (10 h a 10 Hz já são 360 mil valores por sinal, e quem
consulta quer fatias).

Grade: a amostra `i` cobre os quadros `[i * hop_frames, (i + 1) * hop_frames)` a 60 fps. Conversão entre
quadro e amostra é aritmética inteira, sem float, na mesma grade dos marcadores e do gabarito.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, Field

from cronista.domain.evidence import params_hash
from cronista.domain.models import StageResult
from cronista.domain.types import FloatArray

AUDIO_SIGNAL_HOP = 6
"""Padrão: 6 quadros a 60 fps = 0,1 s = 10 Hz."""

SIGNALS_KEY = "signals"
"""Chave em `StageResult.data` onde a etapa lista seus sinais (nome → SignalMeta)."""


def frame_to_index(frame: int, hop_frames: int) -> int:
    """Índice da amostra que contém o quadro."""
    return frame // hop_frames


def index_to_frame(index: int, hop_frames: int) -> int:
    """Primeiro quadro coberto pela amostra."""
    return index * hop_frames


class SignalMeta(BaseModel):
    name: str
    unit: str
    hop_frames: int = Field(gt=0)
    length: int = Field(ge=0)
    path: str
    source_track: str  # `game` ou `mic`
    model: str  # quem produziu: `dsp` para os sinais numéricos
    version: str
    params_hash: str


@dataclass(frozen=True)
class Signal:
    meta: SignalMeta
    values: FloatArray

    @property
    def end_frame(self) -> int:
        """Primeiro quadro depois da última amostra."""
        return index_to_frame(len(self.values), self.meta.hop_frames)

    def slice(self, start_frame: int, end_frame: int) -> FloatArray:
        """Amostras que se sobrepõem a `[start_frame, end_frame)`. Fora da série, devolve vazio."""
        if end_frame <= start_frame:
            return self.values[0:0]
        hop = self.meta.hop_frames
        first = max(0, frame_to_index(start_frame, hop))
        last = min(len(self.values), -(-end_frame // hop))  # teto: a amostra parcial entra
        return self.values[first:last]

    def at_frame(self, frame: int) -> float:
        index = frame_to_index(frame, self.meta.hop_frames)
        if not 0 <= index < len(self.values):
            raise IndexError(f"quadro {frame} fora do sinal '{self.meta.name}' (0..{self.end_frame})")
        return float(self.values[index])


def write_signal(
    out_dir: Path,
    name: str,
    values: npt.ArrayLike,
    *,
    unit: str,
    source_track: str,
    version: str,
    params: dict[str, Any],
    hop_frames: int = AUDIO_SIGNAL_HOP,
    model: str = "dsp",
) -> SignalMeta:
    """Grava o sinal em `<out_dir>/<name>.npy` e devolve o descritor para o `result.json`."""
    array = np.asarray(values, dtype=np.float32)
    if array.ndim != 1:
        raise ValueError(f"sinal '{name}' precisa ser unidimensional, veio {array.ndim}D")
    path = out_dir / f"{name}.npy"
    np.save(path, array)
    return SignalMeta(
        name=name,
        unit=unit,
        hop_frames=hop_frames,
        length=len(array),
        path=str(path),
        source_track=source_track,
        model=model,
        version=version,
        params_hash=params_hash(params),
    )


def load_signal(meta: SignalMeta) -> Signal:
    """Abre o sinal sem ler tudo para a memória (memmap)."""
    values = np.load(meta.path, mmap_mode="r")
    if values.dtype != np.float32 or values.ndim != 1:
        raise ValueError(f"arquivo de sinal inesperado: {meta.path}")
    return Signal(meta, values)


def signal_metas(result: StageResult) -> dict[str, SignalMeta]:
    """Os sinais listados no resultado de uma etapa (vazio se a etapa não produziu nenhum)."""
    raw = result.data.get(SIGNALS_KEY, {})
    return {name: SignalMeta.model_validate(item) for name, item in raw.items()}
