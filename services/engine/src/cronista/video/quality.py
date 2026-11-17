"""Qualidade da análise de vídeo contra o gabarito (Fase 3C-1): precisão, revocação e erro de bordas.

Funções puras sobre intervalos em quadros a 60 fps (sem banco nem GPU, rodam em `dev`). Um trecho previsto
"acerta" um anotado quando os dois se sobrepõem (ou ficam a menos de `tolerance` um do outro);
o erro de bordas é medido só nos pares casados.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cronista.domain.frames import FPS
from cronista.gabarito import Annotation

Interval = tuple[int, int]

VIDEO_CLASSES = ("menu", "loading", "idle", "cinematica", "hud_oculto")
"""Classes visuais do gabarito avaliadas aqui."""


@dataclass(frozen=True)
class VideoClassResult:
    cls: str
    expected: int
    predicted: int
    matched: int
    boundary_err_s: float | None
    """Média do erro absoluto de início e de fim, em segundos, nos pares casados."""
    within_tolerance: int
    """Pares casados com os dois erros de borda dentro da tolerância."""
    false_per_30min: float | None
    """Previstos sem anotado correspondente a cada 30 min (só confiável se o gabarito cobre a sessão toda)."""

    @property
    def precision(self) -> float | None:
        return self.matched / self.predicted if self.predicted else None

    @property
    def recall(self) -> float | None:
        return self.matched / self.expected if self.expected else None


def _touch(a: Interval, b: Interval, tolerance: int) -> bool:
    return a[0] - tolerance < b[1] and b[0] < a[1] + tolerance


def match_pairs(
    expected: Sequence[Interval], predicted: Sequence[Interval], tolerance: int
) -> list[tuple[Interval, Interval]]:
    """Casa um a um, guloso pelo maior encavalamento (desempata pelo início mais próximo)."""
    free = sorted(predicted)
    used = [False] * len(free)
    pairs: list[tuple[Interval, Interval]] = []
    for exp in sorted(expected):
        best: int | None = None
        best_key: tuple[int, int] | None = None
        for idx, pred in enumerate(free):
            if used[idx] or not _touch(exp, pred, tolerance):
                continue
            over = max(0, min(exp[1], pred[1]) - max(exp[0], pred[0]))
            key = (-over, abs(exp[0] - pred[0]))
            if best_key is None or key < best_key:
                best, best_key = idx, key
        if best is not None:
            used[best] = True
            pairs.append((exp, free[best]))
    return pairs


def evaluate_video(
    annotations: Sequence[Annotation],
    predicted: Mapping[str, Sequence[Interval]],
    total_frames: int,
    tolerance_s: float = 2.0,
    classes: Sequence[str] = VIDEO_CLASSES,
) -> list[VideoClassResult]:
    """Uma linha por classe que aparece no gabarito ou nas previsões."""
    tol = round(tolerance_s * FPS)
    minutes = total_frames / FPS / 60
    out: list[VideoClassResult] = []
    for cls in classes:
        expected = [(a.start_frame, a.end_frame) for a in annotations if a.cls == cls]
        pred = list(predicted.get(cls, []))
        if not expected and not pred:
            continue
        pairs = match_pairs(expected, pred, tol)
        errors = [(abs(e[0] - p[0]) + abs(e[1] - p[1])) / 2 / FPS for e, p in pairs]
        within = sum(1 for e, p in pairs if abs(e[0] - p[0]) <= tol and abs(e[1] - p[1]) <= tol)
        false = len(pred) - len(pairs)
        out.append(
            VideoClassResult(
                cls=cls,
                expected=len(expected),
                predicted=len(pred),
                matched=len(pairs),
                boundary_err_s=sum(errors) / len(errors) if errors else None,
                within_tolerance=within,
                false_per_30min=false / minutes * 30 if minutes > 0 else None,
            )
        )
    return out


def _fmt(value: float | None, spec: str = ".2f") -> str:
    return "-" if value is None else format(value, spec)


def render_video_quality(results: Sequence[VideoClassResult], tolerance_s: float) -> str:
    head = (
        f"{'classe':<12}{'anotados':>9}{'previstos':>10}{'casados':>8}{'precisão':>9}{'revocação':>10}"
        f"{'erro borda':>11}{'em ' + format(tolerance_s, 'g') + ' s':>8}{'falsos/30min':>13}"
    )
    lines = [head, "-" * len(head)]
    for r in results:
        err = "-" if r.boundary_err_s is None else f"{r.boundary_err_s:.1f} s"
        lines.append(
            f"{r.cls:<12}{r.expected:>9}{r.predicted:>10}{r.matched:>8}{_fmt(r.precision):>9}"
            f"{_fmt(r.recall):>10}{err:>11}{r.within_tolerance:>8}{_fmt(r.false_per_30min, '.1f'):>13}"
        )
    if not results:
        lines.append("nada a avaliar: sem anotações visuais no gabarito nem eventos de vídeo")
    return "\n".join(lines)
