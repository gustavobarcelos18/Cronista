"""Detector de grito por energia e altura da voz (sem modelo, só CPU), 2C. EXPERIMENTO, desligado da análise:
reprovado no segundo teste (0 de 8 gritos; fala aguda e grito têm a mesma altura e nível).

Por que existe: o AST (janela de 10 s) não pontuou nenhum grito do criador. O que separa grito de
fala empolgada, medido no teste de voz de 2026-11-17, é a altura da voz: grito 330 a 410 Hz, fala
empolgada até 200 Hz. O volume sozinho não basta (a fala animada chega a -16 dBFS, como o grito).
O limitador do OBS achata o pico (~ -6 dBFS), então usa-se o nível médio (RMS), relativo à mediana
da sessão, e a altura (f0) por autocorrelação.

Universal: nada depende de jogo; a linha de base é a própria sessão.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from cronista.audio.ports import Pause, SoundEventSpan
from cronista.audio.signals import FloatArray

ANALYSIS_RATE = 16000


@dataclass(frozen=True)
class ScreamParams:
    frame_s: float = 0.025
    window_s: float = 0.05  # janela da autocorrelação (2 quadros)
    min_f0_hz: float = 80.0
    max_f0_hz: float = 1000.0
    voiced_ratio: float = 0.3  # força mínima do pico de autocorrelação para contar como voz
    floor_db: float = -50.0  # abaixo disso é silêncio e não entra na linha de base
    min_delta_db: float = 9.0  # quanto acima da mediana de fala da sessão
    min_f0_scream_hz: float = 280.0
    max_gap_s: float = 0.3
    min_duration_s: float = 0.3
    block_s: float = 60.0


def _decimate(audio: FloatArray, rate: int) -> tuple[FloatArray, int]:
    """Mono na taxa de análise (média de grupos: basta para f0 até 1 kHz)."""
    if audio.ndim > 1:
        audio = audio.mean(axis=1, dtype=np.float32)
    factor = max(rate // ANALYSIS_RATE, 1)
    if factor > 1:
        usable = len(audio) // factor * factor
        audio = audio[:usable].reshape(-1, factor).mean(axis=1, dtype=np.float32)
    return audio.astype(np.float32, copy=False), rate // factor


def frame_features(audio: FloatArray, rate: int, params: ScreamParams) -> tuple[FloatArray, FloatArray]:
    """Por quadro de `frame_s`: nível RMS em dBFS e f0 em Hz (0 se não houver voz)."""
    hop = int(params.frame_s * rate)
    win = int(params.window_s * rate)
    count = (len(audio) - win) // hop + 1
    if count <= 0:
        return np.zeros(0, dtype=np.float32), np.zeros(0, dtype=np.float32)
    index = np.arange(count)[:, None] * hop + np.arange(win)[None, :]
    frames = audio[index]
    rms = np.sqrt((frames**2).mean(axis=1))
    level = (20 * np.log10(rms + 1e-9)).astype(np.float32)
    centered = frames - frames.mean(axis=1, keepdims=True)
    nfft = 2 * win
    spectrum = np.fft.rfft(centered, nfft, axis=1)
    ac = np.fft.irfft(np.abs(spectrum) ** 2, nfft, axis=1)[:, :win]
    lo, hi = int(rate / params.max_f0_hz), min(int(rate / params.min_f0_hz), win - 1)
    peak_lag = lo + np.argmax(ac[:, lo:hi], axis=1)
    strength = ac[np.arange(count), peak_lag] / (ac[:, 0] + 1e-12)
    f0 = np.where(strength > params.voiced_ratio, rate / peak_lag, 0.0).astype(np.float32)
    return level, f0


def find_screams(level: FloatArray, f0: FloatArray, params: ScreamParams) -> list[tuple[float, float, float]]:
    """(início, fim, confiança) em segundos, a partir dos arrays por quadro."""
    voiced = level > params.floor_db
    if not voiced.any():
        return []
    baseline = float(np.median(level[voiced]))
    delta = level - baseline
    hit = (delta >= params.min_delta_db) & (f0 >= params.min_f0_scream_hz)
    gap = max(int(params.max_gap_s / params.frame_s), 1)
    spans: list[list[int]] = []
    for i in np.flatnonzero(hit):
        if spans and i - spans[-1][1] <= gap:
            spans[-1][1] = int(i)
        else:
            spans.append([int(i), int(i)])
    out: list[tuple[float, float, float]] = []
    for first, last in spans:
        start, end = first * params.frame_s, (last + 1) * params.frame_s + (params.window_s - params.frame_s)
        if end - start < params.min_duration_s:
            continue
        seg_delta = float(delta[first : last + 1].max())
        seg_f0 = float(np.median(f0[first : last + 1][f0[first : last + 1] > 0]))
        score = 0.5 * min(seg_delta / 15.0, 1.0) + 0.5 * min(max(seg_f0 - 200.0, 0.0) / 200.0, 1.0)
        out.append((start, end, min(max(score, 0.05), 1.0)))
    return out


class ScreamHeuristic:
    """Classificador (porta `SoundEventClassifier`) que só emite `grito`. CPU, sem modelo baixado."""

    name = "grito-energia-f0"
    version = "1"

    def __init__(self, params: ScreamParams | None = None) -> None:
        self.params = params or ScreamParams()
        self.options: dict[str, Any] = dict(self.params.__dict__)

    def classify(self, wav: Path, *, pause: Pause) -> list[SoundEventSpan]:
        p = self.params
        levels: list[FloatArray] = []
        pitches: list[FloatArray] = []
        with sf.SoundFile(str(wav)) as handle:
            rate = handle.samplerate
            per_block = int(p.block_s * rate)
            while True:
                pause()
                data = handle.read(per_block, dtype="float32", always_2d=True)
                if len(data) == 0:
                    break
                audio, analysis_rate = _decimate(data.mean(axis=1, dtype=np.float32), rate)
                # Completa o fim para o bloco render exatamente `len/hop` quadros e o tempo não derivar.
                tail = int((p.window_s - p.frame_s) * analysis_rate)
                level, f0 = frame_features(np.pad(audio, (0, tail)), analysis_rate, p)
                levels.append(level)
                pitches.append(f0)
        if not levels:
            return []
        spans = find_screams(np.concatenate(levels), np.concatenate(pitches), p)
        return [SoundEventSpan(label="grito", start_s=s, end_s=e, score=c) for s, e, c in spans]
