"""Métricas da relevância contra o gabarito (Fase 4): momentos no topo, farm como farm, compressão."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from cronista.domain.frames import FPS
from cronista.gabarito import Annotation
from cronista.relevance.engine import Segment, kept_seconds

DISCARDED = ("descartavel",)
FARM = "farm"


@dataclass(frozen=True)
class RelevanceQuality:
    moments_expected: int
    moments_in_top: int
    top_n: int
    farm_recall: float | None
    farm_precision: float | None
    raw_s: int
    kept_s: float

    @property
    def moment_recall(self) -> float | None:
        return self.moments_in_top / self.moments_expected if self.moments_expected else None

    @property
    def compression(self) -> float | None:
        """Quantos segundos de gravação para cada segundo de material mantido (sem contar a narração)."""
        return self.raw_s / self.kept_s if self.kept_s else None


def _overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def top_candidates(segments: Sequence[Segment], top_n: int) -> list[Segment]:
    ranked = [s for s in segments if s.classe not in DISCARDED]
    return sorted(ranked, key=lambda s: -s.score)[:top_n]


def evaluate_relevance(
    annotations: Sequence[Annotation],
    segments: Sequence[Segment],
    top_n: int = 30,
    keep_score: float = 0.35,
) -> RelevanceQuality:
    """Momento do gabarito "aparece" se algum dos `top_n` candidatos se sobrepõe a ele."""
    moments = [(a.start_frame / FPS, a.end_frame / FPS) for a in annotations if a.cls == "momento"]
    top = top_candidates(segments, top_n)
    hit = sum(1 for m in moments if any(_overlap(m, (s.start_s, s.end_s)) > 0 for s in top))
    farm_truth = [(a.start_frame / FPS, a.end_frame / FPS) for a in annotations if a.cls == "farm"]
    farm_pred = [(float(s.start_s), float(s.end_s)) for s in segments if s.classe == FARM]
    truth_s = sum(b - a for a, b in farm_truth)
    pred_s = sum(b - a for a, b in farm_pred)
    covered = sum(_overlap(t, p) for t in farm_truth for p in farm_pred)
    raw = max((s.end_s for s in segments), default=0)
    kept = round(sum(kept_seconds(s, keep_score) for s in segments), 1)
    return RelevanceQuality(
        len(moments),
        hit,
        top_n,
        covered / truth_s if truth_s else None,
        covered / pred_s if pred_s else None,
        raw,
        kept,
    )


def render_quality(q: RelevanceQuality) -> str:
    def pct(v: float | None) -> str:
        return "-" if v is None else f"{v:.0%}"

    comp = "-" if q.compression is None else f"{q.compression:.1f}x"
    return "\n".join(
        [
            f"momentos do gabarito no top {q.top_n}: {q.moments_in_top}/{q.moments_expected} "
            f"({pct(q.moment_recall)}; meta 85%)",
            f"farm: revocação {pct(q.farm_recall)}, precisão {pct(q.farm_precision)}",
            f"compressão: {q.raw_s} s de gravação, {q.kept_s} s mantidos ({comp})",
        ]
    )
