"""Sinais visuais por quadro amostrado, em CPU e sem modelo (Fase 3A).

Tudo é medido sobre quadros em cinza 160x90 e normalizado para 0-1 (exceto `shift`, em pixels desse quadro).
Nada depende de jogo: o que vale é o comportamento da tela (parada, escura, cheia de bordas, deslocando).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from cronista.video.frames import GrayFrames

FloatArray = npt.NDArray[np.float32]

SIGNAL_NAMES = (
    "motion",
    "still",
    "luma_mean",
    "luma_std",
    "edge_density",
    "shift",
    "shift_conf",
    "hist_diff",
)


@dataclass(frozen=True)
class SignalParams:
    still_tolerance: int = 4  # diferença (0-255) abaixo da qual o pixel conta como parado
    edge_threshold: int = 40  # |dx| + |dy| (0-510) acima do qual o pixel conta como borda
    hist_bins: int = 16
    flat_std: float = 0.02  # abaixo disso o quadro é liso e o deslocamento global não faz sentido


@dataclass
class BlockSignals:
    values: dict[str, FloatArray]
    last_frame: GrayFrames
    last_hist: FloatArray


def _hist(frames: GrayFrames, bins: int) -> FloatArray:
    flat = (frames.reshape(len(frames), -1).astype(np.int32) * bins // 256).clip(0, bins - 1)
    out = np.zeros((len(frames), bins), dtype=np.float32)
    for b in range(bins):
        out[:, b] = (flat == b).mean(axis=1)
    return out


def _edge_density(frames: GrayFrames, threshold: int) -> FloatArray:
    f = frames.astype(np.int16)
    dx = np.abs(np.diff(f, axis=2))[:, :-1, :]
    dy = np.abs(np.diff(f, axis=1))[:, :, :-1]
    return ((dx + dy) > threshold).reshape(len(frames), -1).mean(axis=1).astype(np.float32)


SHIFT_CHUNK = 100
"""Quadros por pedaço na FFT: o rfft2 devolve complex128 e um bloco inteiro (1500) passaria de 1 GB."""


def _global_shift(
    prev: GrayFrames, cur: GrayFrames, flat: npt.NDArray[np.bool_]
) -> tuple[FloatArray, FloatArray]:
    """Deslocamento global entre quadros por correlação de fase: (módulo em px, confiança de 0 a 1)."""
    parts = [
        _chunk_shift(prev[i : i + SHIFT_CHUNK], cur[i : i + SHIFT_CHUNK], flat[i : i + SHIFT_CHUNK])
        for i in range(0, len(cur), SHIFT_CHUNK)
    ]
    return (
        np.concatenate([m for m, _ in parts]).astype(np.float32),
        np.concatenate([c for _, c in parts]).astype(np.float32),
    )


def _chunk_shift(
    prev: GrayFrames, cur: GrayFrames, flat: npt.NDArray[np.bool_]
) -> tuple[FloatArray, FloatArray]:
    a = prev.astype(np.float32) - prev.mean(axis=(1, 2), keepdims=True)
    b = cur.astype(np.float32) - cur.mean(axis=(1, 2), keepdims=True)
    cross = np.fft.rfft2(b) * np.conj(np.fft.rfft2(a))
    cross /= np.abs(cross) + 1e-9
    corr = np.fft.irfft2(cross, s=a.shape[1:])
    h, w = corr.shape[1:]
    flat_idx = corr.reshape(len(corr), -1).argmax(axis=1)
    peak = corr.reshape(len(corr), -1).max(axis=1)
    dy, dx = np.divmod(flat_idx, w)
    dy = np.where(dy > h // 2, dy - h, dy)
    dx = np.where(dx > w // 2, dx - w, dx)
    magnitude = np.hypot(dx, dy).astype(np.float32)
    confidence = np.clip(peak, 0.0, 1.0).astype(np.float32)
    magnitude[flat] = 0.0
    confidence[flat] = 0.0
    return magnitude, confidence


def block_signals(
    frames: GrayFrames,
    previous: tuple[GrayFrames, FloatArray] | None,
    params: SignalParams,
) -> BlockSignals:
    """Sinais de um bloco; `previous` (último quadro e histograma do bloco anterior) dá continuidade."""
    n = len(frames)
    hist = _hist(frames, params.hist_bins)
    if previous is None:
        before = np.concatenate([frames[:1], frames[:-1]])
        before_hist = np.concatenate([hist[:1], hist[:-1]])
    else:
        prev_frame, prev_hist = previous
        before = np.concatenate([prev_frame, frames[:-1]])
        before_hist = np.concatenate([prev_hist[None, :], hist[:-1]])
    diff = np.abs(frames.astype(np.int16) - before.astype(np.int16))
    luma_std = (frames.reshape(n, -1).std(axis=1) / 255.0).astype(np.float32)
    shift, shift_conf = _global_shift(before, frames, luma_std < params.flat_std)
    values: dict[str, FloatArray] = {
        "motion": (diff.reshape(n, -1).mean(axis=1) / 255.0).astype(np.float32),
        "still": (diff.reshape(n, -1) < params.still_tolerance).mean(axis=1).astype(np.float32),
        "luma_mean": (frames.reshape(n, -1).mean(axis=1) / 255.0).astype(np.float32),
        "luma_std": luma_std,
        "edge_density": _edge_density(frames, params.edge_threshold),
        "shift": shift,
        "shift_conf": shift_conf,
        "hist_diff": (np.abs(hist - before_hist).sum(axis=1) / 2.0).astype(np.float32),
    }
    return BlockSignals(values, frames[-1:], hist[-1])
