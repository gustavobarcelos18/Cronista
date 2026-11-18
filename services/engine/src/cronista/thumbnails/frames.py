# ruff: noqa: E501
"""Frames candidatos a thumbnail (Fase 9B): amostragem dos picos do vídeo e nota de qualidade por heurística.

Puro e determinístico (numpy, sem modelo): a nota do momento vem do story-pack (Fase 4/5) e a qualidade do frame
(nitidez, contraste, exposição e composição) é medida sobre uma imagem em tons de cinza. O FFmpeg que entrega os
pixels fica em `render.py`. Mesma entrada, mesma escolha.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

SAMPLES_PER_BEAT = 5
MAX_SPAN_S = 60.0
"""Segmentos longos são amostrados só em volta do meio (o pico costuma estar longe das pontas)."""
TOP_BEATS = 8
MIN_GAP_S = 20.0
"""Dois frames do mesmo arquivo mais próximos que isso viram variações quase iguais; só o melhor fica."""
SCORE_WEIGHT = 0.6
QUALITY_WEIGHT = 0.4
_THIRDS = ((1 / 3, 1 / 3), (2 / 3, 1 / 3), (1 / 3, 2 / 3), (2 / 3, 2 / 3), (0.5, 0.5))


@dataclass(frozen=True)
class FrameMetrics:
    sharpness: float
    contrast: float
    exposure: float
    composition: float

    @property
    def quality(self) -> float:
        """0 a 1. A exposição (tela preta ou estourada) multiplica: um frame escuro nunca ganha por ser nítido."""
        base = 0.5 * self.sharpness + 0.2 * self.contrast + 0.3 * self.composition
        return round(base * self.exposure, 6)


GrayImage = NDArray[np.floating[Any]] | NDArray[np.uint8]


def measure_frame(gray: GrayImage) -> FrameMetrics:
    """Mede um frame em tons de cinza (2D, 0 a 255)."""
    img = np.asarray(gray, dtype=np.float64)
    if img.ndim != 2 or min(img.shape) < 8:
        raise ValueError("o frame precisa ser uma imagem 2D de pelo menos 8x8")
    lap = (
        img[:-2, 1:-1] + img[2:, 1:-1] + img[1:-1, :-2] + img[1:-1, 2:] - 4 * img[1:-1, 1:-1]
    )  # Laplaciano: borda forte = imagem nítida
    sharp = float(lap.var())
    sharpness = sharp / (sharp + 200.0)
    contrast = min(1.0, float(img.std()) / 64.0)
    dark = float((img < 16).mean())
    blown = float((img > 240).mean())
    exposure = max(0.0, 1.0 - dark - blown)
    gy, gx = np.gradient(img)
    energy = np.hypot(gx, gy)
    total = float(energy.sum())
    if total <= 0:
        composition = 0.0
    else:
        ys, xs = np.indices(img.shape)
        cx = float((xs * energy).sum() / total) / img.shape[1]
        cy = float((ys * energy).sum() / total) / img.shape[0]
        nearest = min(np.hypot(cx - px, cy - py) for px, py in _THIRDS)
        composition = max(0.0, 1.0 - nearest / 0.35)  # o interesse perto dos pontos de terço/centro
    return FrameMetrics(round(sharpness, 6), round(contrast, 6), round(exposure, 6), round(composition, 6))


@dataclass(frozen=True)
class Moment:
    """Um trecho de interesse do vídeo (um beat do story-pack)."""

    file_id: int
    segment_id: int
    start_s: float
    end_s: float
    score: float
    beat: str
    classe: str


@dataclass(frozen=True)
class Sample:
    moment: Moment
    t_s: float


@dataclass(frozen=True)
class ScoredFrame:
    file_id: int
    segment_id: int
    t_s: float
    score: float
    """Nota final: 60% a nota do momento, 40% a qualidade do frame."""
    moment_score: float
    quality: float
    beat: str
    classe: str


def moments_from_story_pack(story_pack: Mapping[str, Any], top: int = TOP_BEATS) -> list[Moment]:
    """Os beats de maior nota (empate: id do segmento), com arquivo e janela em segundos."""
    flat = [b for c in story_pack.get("capitulos", []) for b in c.get("beats", [])]
    flat.sort(key=lambda b: (-float(b["nota"]), int(b["segmento_id"])))
    return [
        Moment(
            int(b["arquivo_id"]),
            int(b["segmento_id"]),
            float(b["inicio_s"]),
            float(b["fim_s"]),
            float(b["nota"]),
            str(b["beat"]),
            str(b["classe"]),
        )
        for b in flat[:top]
    ]


def sample_times(moment: Moment, count: int = SAMPLES_PER_BEAT) -> list[float]:
    """Instantes igualmente espaçados dentro do trecho (limitado a `MAX_SPAN_S` em volta do meio)."""
    span = min(moment.end_s - moment.start_s, MAX_SPAN_S)
    if span <= 0:
        return [round(moment.start_s, 3)]
    mid = (moment.start_s + moment.end_s) / 2
    first = mid - span / 2
    return [round(first + span * (i + 1) / (count + 1), 3) for i in range(count)]


def plan_samples(moments: Sequence[Moment], count: int = SAMPLES_PER_BEAT) -> list[Sample]:
    return [Sample(m, t) for m in moments for t in sample_times(m, count)]


def score_frame(sample: Sample, metrics: FrameMetrics) -> ScoredFrame:
    m = sample.moment
    final = SCORE_WEIGHT * m.score + QUALITY_WEIGHT * metrics.quality
    return ScoredFrame(
        m.file_id, m.segment_id, sample.t_s, round(final, 6), m.score, metrics.quality, m.beat, m.classe
    )


def pick_frames(
    scored: Sequence[ScoredFrame], count: int = 3, min_gap_s: float = MIN_GAP_S
) -> list[ScoredFrame]:
    """Os melhores frames, no máximo um por segmento e sem dois muito próximos no mesmo arquivo."""
    ranked = sorted(scored, key=lambda f: (-f.score, f.file_id, f.t_s))
    chosen: list[ScoredFrame] = []
    for frame in ranked:
        if len(chosen) >= count:
            break
        if any(c.segment_id == frame.segment_id for c in chosen):
            continue
        if any(c.file_id == frame.file_id and abs(c.t_s - frame.t_s) < min_gap_s for c in chosen):
            continue
        chosen.append(frame)
    return chosen
