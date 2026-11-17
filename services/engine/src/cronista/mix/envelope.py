"""Ducking (puro): intervalos em quadros da timeline → ganho suave por amostra.

O ganho é calculado numa taxa de controle baixa (200 Hz) com ataque e soltura (rampas), e só é expandido
para a taxa de áudio por trecho (`gain_at`), para uma hora de áudio não pedir um vetor gigante.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from cronista.assembly.plan import EditItem, Mode, Track
from cronista.domain.frames import FPS
from cronista.story.models import ScriptLine
from cronista.story.script import estimate_seconds

FloatArray = npt.NDArray[np.float32]
CONTROL_RATE = 200


@dataclass(frozen=True)
class DuckParams:
    duck_db: float = -12.0
    attack_s: float = 0.05
    release_s: float = 0.4
    pad_s: float = 0.15
    """Folga antes e depois de cada intervalo, para o jogo já estar baixo quando a voz entra."""


def timeline_intervals(
    plan_items: Sequence[EditItem], file_ranges: Mapping[int, Sequence[tuple[int, int]]]
) -> list[tuple[int, int]]:
    """Intervalos em quadros de arquivo (`file_id` → `[(ini, fim)]`) levados para quadros da timeline.

    Só trechos de V1 em velocidade normal têm áudio; no timelapse não há voz nem jogo.
    """
    out: list[tuple[int, int]] = []
    for item in plan_items:
        if item.track != Track.V1 or item.mode == Mode.TIMELAPSE:
            continue
        for a, b in file_ranges.get(item.file_id, ()):
            lo, hi = max(a, item.in_frame), min(b, item.out_frame)
            if hi > lo:
                out.append(
                    (item.timeline_start + lo - item.in_frame, item.timeline_start + hi - item.in_frame)
                )
    return merge_intervals(out)


def narration_cues(
    plan_items: Sequence[EditItem], lines: Sequence[ScriptLine]
) -> list[tuple[int, int, ScriptLine]]:
    """Onde o roteiro prevê cada fala, em quadros da timeline (entra em `start_s` ou no começo do trecho).

    Linha de segmento que não está na montagem (ou está em timelapse) é ignorada.
    """
    by_segment = {i.segment_id: i for i in plan_items if i.track == Track.V1 and i.speed == 1}
    out: list[tuple[int, int, ScriptLine]] = []
    for line in lines:
        item = by_segment.get(line.segment_id)
        if item is None:
            continue
        seconds = line.est_s if line.est_s is not None else estimate_seconds(line.text)
        start_file = round(line.start_s * FPS) if line.start_s is not None else item.in_frame
        start_file = min(max(start_file, item.in_frame), item.out_frame)
        start = item.timeline_start + start_file - item.in_frame
        end = min(start + round(seconds * FPS), item.timeline_end)
        if end > start:
            out.append((start, end, line))
    return sorted(out, key=lambda c: c[0])


def narration_intervals(plan_items: Sequence[EditItem], lines: Sequence[ScriptLine]) -> list[tuple[int, int]]:
    return merge_intervals([(a, b) for a, b, _ in narration_cues(plan_items, lines)])


def merge_intervals(intervals: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for a, b in sorted(intervals):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def gain_curve(total_frames: int, intervals: Sequence[tuple[int, int]], params: DuckParams) -> FloatArray:
    """Ganho linear a `CONTROL_RATE` por segundo, de 1.0 (fora) até `duck_db` (dentro), com rampas."""
    n = max(1, round(total_frames / FPS * CONTROL_RATE)) + 1
    target = np.ones(n, dtype=np.float64)
    low = 10 ** (params.duck_db / 20)
    pad = round(params.pad_s * CONTROL_RATE)
    for a, b in intervals:
        lo = max(0, round(a / FPS * CONTROL_RATE) - pad)
        hi = min(n, round(b / FPS * CONTROL_RATE) + pad)
        target[lo:hi] = low
    attack = 1 - np.exp(-1 / max(params.attack_s * CONTROL_RATE, 1e-6))
    release = 1 - np.exp(-1 / max(params.release_s * CONTROL_RATE, 1e-6))
    out = np.empty(n, dtype=np.float64)
    g = 1.0
    for i in range(n):
        goal = target[i]
        g += (goal - g) * (attack if goal < g else release)
        out[i] = g
    return out.astype(np.float32)


def gain_at(curve: FloatArray, first_sample: int, count: int, rate: int) -> FloatArray:
    """Ganho por amostra de `[first_sample, first_sample + count)`, interpolado da curva de controle."""
    positions = (np.arange(first_sample, first_sample + count, dtype=np.float64) / rate) * CONTROL_RATE
    return np.interp(positions, np.arange(len(curve)), curve).astype(np.float32)
