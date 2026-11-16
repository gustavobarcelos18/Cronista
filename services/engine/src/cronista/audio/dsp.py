"""Sinais numéricos do áudio em CPU: energia, fluxo espectral, novidade e periodicidade.

Tudo é **relativo à sessão**: nada aqui depende de jogo (plano, seção 3). O que pontua é a mudança em
relação à linha de base da sessão (mediana móvel), não a altura do som. O recorte por contexto visual
entra na Fase 3.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from numpy.lib.stride_tricks import sliding_window_view

from cronista.audio.signals import FloatArray
from cronista.domain.frames import FPS

DB_FLOOR = -120.0
EPS = 1e-9


@dataclass(frozen=True)
class DspParams:
    hop_frames: int = 6
    n_fft: int = 1024
    flux_rate_hz: int = 100
    baseline_s: float = 300.0
    baseline_step_s: float = 30.0
    novelty_max: float = 30.0
    periodicity_window_s: float = 20.0
    periodicity_stride_s: float = 1.0
    periodicity_min_lag_s: float = 0.3
    periodicity_max_lag_s: float = 4.0
    block_s: float = 60.0

    def as_dict(self) -> dict[str, float | int]:
        return dict(self.__dict__)

    @property
    def hop_s(self) -> float:
        return self.hop_frames / FPS


def hop_samples(sample_rate: int, hop_frames: int) -> int:
    """Amostras de áudio por amostra de sinal. Exige divisão exata para a grade de quadros não derivar."""
    total = sample_rate * hop_frames
    if total % FPS:
        raise ValueError(f"{sample_rate} Hz não divide a grade de {hop_frames} quadros a {FPS} fps")
    return total // FPS


def iter_mono_blocks(path: Path, block_s: float) -> Iterator[tuple[FloatArray, int]]:
    """Lê o WAV em blocos (RF64 incluso), já em mono float32. Nunca carrega o arquivo inteiro."""
    with sf.SoundFile(str(path)) as handle:
        rate = handle.samplerate
        for block in handle.blocks(blocksize=int(block_s * rate), dtype="float32", always_2d=True):
            yield block.mean(axis=1, dtype=np.float32), rate


class _FluxExtractor:
    """Fluxo espectral em log (positivo) a `flux_rate_hz`, em streaming, com janelas centradas."""

    def __init__(self, sample_rate: int, n_fft: int, rate_hz: int) -> None:
        if sample_rate % rate_hz:
            raise ValueError(f"{sample_rate} Hz não é múltiplo de {rate_hz} Hz")
        self.hop = sample_rate // rate_hz
        self.n_fft = n_fft
        self.window = np.hanning(n_fft).astype(np.float32)
        self.buffer: FloatArray = np.zeros(n_fft // 2, dtype=np.float32)  # preenchimento à esquerda
        self.previous: FloatArray | None = None
        self.out: list[FloatArray] = []

    def feed(self, samples: FloatArray) -> None:
        self.buffer = np.concatenate([self.buffer, samples])
        self._drain()

    def finish(self) -> FloatArray:
        self.feed(np.zeros(self.n_fft // 2, dtype=np.float32))  # preenchimento à direita
        return np.concatenate(self.out) if self.out else np.zeros(0, dtype=np.float32)

    def _drain(self) -> None:
        if len(self.buffer) < self.n_fft:
            return
        count = (len(self.buffer) - self.n_fft) // self.hop + 1
        frames = sliding_window_view(self.buffer, self.n_fft)[:: self.hop][:count]
        spectrum = np.abs(np.fft.rfft(frames * self.window, axis=1))
        db = (20.0 * np.log10(spectrum + 1e-5)).astype(np.float32)
        if self.previous is not None:
            db = np.concatenate([self.previous[None, :], db])
        diff = np.maximum(db[1:] - db[:-1], 0.0)
        flux = diff.mean(axis=1, dtype=np.float32)
        if self.previous is None:
            flux = np.concatenate([np.zeros(1, dtype=np.float32), flux])  # o 1º quadro não tem anterior
        self.previous = db[-1]
        self.out.append(flux)
        self.buffer = self.buffer[count * self.hop :]


@dataclass(frozen=True)
class BaseSignals:
    energy_db: FloatArray  # RMS por amostra de sinal, em dBFS
    onset: FloatArray  # fluxo espectral máximo por amostra de sinal (dB)


def analyze_track(
    path: Path,
    params: DspParams,
    *,
    with_onset: bool,
    between_blocks: Callable[[], None] = lambda: None,
) -> BaseSignals:
    """Energia e (opcional) fluxo espectral de uma faixa, em blocos. `between_blocks` é a pausa de GPU/OBS."""
    energy: list[FloatArray] = []
    pending: FloatArray = np.zeros(0, dtype=np.float32)
    flux: _FluxExtractor | None = None
    hop = 0
    for block, rate in iter_mono_blocks(path, params.block_s):
        between_blocks()
        if flux is None:
            hop = hop_samples(rate, params.hop_frames)
            if with_onset:
                flux = _FluxExtractor(rate, params.n_fft, params.flux_rate_hz)
                if hop % flux.hop:
                    raise ValueError("o passo do fluxo precisa dividir o passo do sinal")
        if flux is not None:
            flux.feed(block)
        pending = np.concatenate([pending, block])
        whole = len(pending) // hop
        if whole:
            energy.append(_rms_db(pending[: whole * hop].reshape(whole, hop)))
            pending = pending[whole * hop :]
    if len(pending):  # último passo, parcial: RMS sobre o que existe
        energy.append(_rms_db(pending.reshape(1, -1)))
    energy_db = np.concatenate(energy) if energy else np.zeros(0, dtype=np.float32)
    if flux is None:
        return BaseSignals(energy_db, np.zeros(len(energy_db), dtype=np.float32))
    per_hop = hop // flux.hop
    return BaseSignals(energy_db, _max_per_hop(flux.finish(), per_hop, len(energy_db)))


def _rms_db(segments: FloatArray) -> FloatArray:
    rms = np.sqrt(np.mean(np.square(segments, dtype=np.float32), axis=1))
    return np.maximum(20.0 * np.log10(rms + EPS), DB_FLOOR).astype(np.float32)


def _max_per_hop(flux: FloatArray, per_hop: int, length: int) -> FloatArray:
    padded = per_hop * length
    if len(flux) < padded:
        flux = np.concatenate([flux, np.zeros(padded - len(flux), dtype=np.float32)])
    return flux[:padded].reshape(length, per_hop).max(axis=1)


def rolling_median_mad(values: FloatArray, window: int, step: int) -> tuple[FloatArray, FloatArray]:
    """Mediana e MAD móveis (janela de `window` amostras), calculadas a cada `step` e interpoladas.

    Calcular em passos mantém o custo baixo em sessões de horas; a linha de base não precisa de mais.
    """
    n = len(values)
    if n == 0:
        empty = np.zeros(0, dtype=np.float32)
        return empty, empty
    centers = np.arange(min(step // 2, n - 1), n, step)
    half = max(window // 2, 1)
    med = np.empty(len(centers), dtype=np.float64)
    mad = np.empty(len(centers), dtype=np.float64)
    for i, center in enumerate(centers):
        segment = values[max(0, center - half) : min(n, center + half + 1)]
        med[i] = np.median(segment)
        mad[i] = np.median(np.abs(segment - med[i]))
    grid = np.arange(n)
    return (
        np.interp(grid, centers, med).astype(np.float32),
        np.interp(grid, centers, mad).astype(np.float32),
    )


def novelty(onset: FloatArray, params: DspParams) -> FloatArray:
    """Quanto o fluxo espectral passa da linha de base da sessão, em desvios robustos (≥ 0).

    Passos e ruído de fundo repetitivos ficam perto de 0; um som novo (explosão, grito, impacto) dispara.
    """
    per_second = round(1.0 / params.hop_s)
    window = int(params.baseline_s * per_second)
    step = max(int(params.baseline_step_s * per_second), 1)
    med, mad = rolling_median_mad(onset, window, step)
    scale = np.maximum(np.maximum(1.4826 * mad, 0.1 * np.abs(med)), 1e-3)
    clipped: FloatArray = np.clip((onset - med) / scale, 0.0, params.novelty_max).astype(np.float32)
    return clipped


def energy_above_baseline(energy_db: FloatArray, params: DspParams) -> FloatArray:
    """dB acima da mediana móvel da sessão (pode ser negativo: o criador está mais quieto que o normal)."""
    per_second = round(1.0 / params.hop_s)
    med, _ = rolling_median_mad(
        energy_db, int(params.baseline_s * per_second), max(int(params.baseline_step_s * per_second), 1)
    )
    return (energy_db - med).astype(np.float32)


def periodicity(onset: FloatArray, params: DspParams) -> FloatArray:
    """Força da repetição regular (de 0 a 1): maior pico da autocorrelação do `onset` em janelas de ~20 s.

    Passos, mineração e corte de árvore repetem em ritmo constante (lag de 0,3 a 4 s). É sinal de rotina, não
    de acontecimento. Janela sem variação (silêncio ou ruído estável demais) vale 0.
    """
    per_second = round(1.0 / params.hop_s)
    window = int(params.periodicity_window_s * per_second)
    stride = max(int(params.periodicity_stride_s * per_second), 1)
    min_lag = max(round(params.periodicity_min_lag_s * per_second), 1)
    max_lag = int(params.periodicity_max_lag_s * per_second)
    n = len(onset)
    if n < window or window <= max_lag:
        window = n
    if window <= max_lag + 1:
        return np.zeros(n, dtype=np.float32)

    starts = np.arange(0, n - window + 1, stride)
    windows = sliding_window_view(onset.astype(np.float64), window)[starts]
    windows = windows - windows.mean(axis=1, keepdims=True)
    energy = np.sum(windows * windows, axis=1)
    best = np.zeros(len(starts))
    for lag in range(min_lag, max_lag + 1):
        ac = np.sum(windows[:, :-lag] * windows[:, lag:], axis=1)
        best = np.maximum(best, ac)
    flat = energy < 1e-6 * window
    strength = np.where(flat, 0.0, np.clip(best / np.maximum(energy, EPS), 0.0, 1.0))
    centers = starts + window // 2
    return np.interp(np.arange(n), centers, strength).astype(np.float32)
