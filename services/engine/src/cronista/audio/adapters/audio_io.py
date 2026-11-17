"""Leitura de trechos de WAV em mono float32 a 16 kHz (a taxa dos três modelos), por bloco ou intervalo."""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from cronista.audio.signals import FloatArray

MODEL_RATE = 16000


def package_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "desconhecida"


def duration_s(wav: Path) -> float:
    with sf.SoundFile(str(wav)) as handle:
        return float(handle.frames / handle.samplerate)


def _resample(audio: FloatArray, rate: int) -> FloatArray:
    if rate == MODEL_RATE or len(audio) == 0:
        return audio
    torch: Any = importlib.import_module("torch")
    functional: Any = importlib.import_module("torchaudio.functional")
    out = functional.resample(torch.from_numpy(audio), rate, MODEL_RATE)
    return np.asarray(out.numpy(), dtype=np.float32)


def read_segment(wav: Path, start_s: float, end_s: float) -> FloatArray:
    """O intervalo `[start_s, end_s)` em mono a 16 kHz. Fora do arquivo, completa com silêncio."""
    with sf.SoundFile(str(wav)) as handle:
        rate = handle.samplerate
        first = round(start_s * rate)
        count = max(round((end_s - start_s) * rate), 0)
        lead = max(-first, 0)
        handle.seek(min(max(first, 0), handle.frames))
        data = handle.read(max(count - lead, 0), dtype="float32", always_2d=True)
    mono = data.mean(axis=1, dtype=np.float32) if len(data) else np.zeros(0, dtype=np.float32)
    padded = np.concatenate([np.zeros(lead, dtype=np.float32), mono])
    padded = np.concatenate([padded, np.zeros(count - len(padded), dtype=np.float32)])
    return _resample(padded, rate)


def iter_blocks(wav: Path, block_s: float) -> Iterator[tuple[float, FloatArray]]:
    """Blocos consecutivos de `block_s` segundos: (início em segundos, áudio mono a 16 kHz)."""
    total = duration_s(wav)
    start = 0.0
    while start < total:
        end = min(start + block_s, total)
        yield start, read_segment(wav, start, end)
        start = end
