"""Métricas de qualidade da análise de áudio contra o gabarito (Fase 2C, tarefa 1).

Funções puras sobre intervalos em quadros inteiros a 60 fps: nada de banco, modelo ou GPU, então rodam em
`dev`. Convenção do gabarito: na classe `fala`, a `nota` é o **texto dito** (referência do WER).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from cronista.domain.frames import FPS
from cronista.gabarito import Annotation

Interval = tuple[int, int]
"""(início, fim) em quadros; fim exclusivo."""


def normalize_text(text: str) -> list[str]:
    """Minúsculas, sem acento nem pontuação, em palavras. WER compara só o que foi dito, não a grafia."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    plain = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9]+", plain)


def wer(reference: str, hypothesis: str) -> float | None:
    """Minúsculas, sem acento nem pontuação, em palavras (WER compara o dito, não a grafia)."""
    ref, hyp = normalize_text(reference), normalize_text(hypothesis)
    if not ref:
        return None
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, start=1):
        current = [i]
        for j, h in enumerate(hyp, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (r != h)))
        previous = current
    return previous[-1] / len(ref)


def overlap(a: Interval, b: Interval) -> int:
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def _near(a: Interval, b: Interval, tolerance: int) -> bool:
    return a[0] - tolerance < b[1] and b[0] < a[1] + tolerance


@dataclass(frozen=True)
class Detection:
    """Resultado de uma classe: precisão e revocação com tolerância em quadros."""

    true_positives: int
    predicted: int
    expected: int

    @property
    def precision(self) -> float | None:
        return self.true_positives / self.predicted if self.predicted else None

    @property
    def recall(self) -> float | None:
        return self.true_positives / self.expected if self.expected else None


def match_events(
    expected: Sequence[Interval], predicted: Sequence[Interval], tolerance_frames: int
) -> Detection:
    """Casa um a um (guloso, por ordem de início) previsto e esperado que se tocam dentro da tolerância."""
    free = sorted(predicted)
    used = [False] * len(free)
    hits = 0
    for exp in sorted(expected):
        for idx, pred in enumerate(free):
            if not used[idx] and _near(exp, pred, tolerance_frames):
                used[idx] = True
                hits += 1
                break
    return Detection(hits, len(free), len(expected))


def false_events_per_10_min(
    forbidden: Sequence[Interval], predicted: Sequence[Interval], total_frames: int
) -> float:
    """Eventos previstos em trechos que NÃO devem gerar evento (teclado, respiração), por 10 min de vídeo."""
    false_positives = sum(1 for p in predicted if any(overlap(p, f) > 0 for f in forbidden))
    minutes = total_frames / FPS / 60
    return false_positives / minutes * 10 if minutes > 0 else 0.0


def routine_recall(
    expected: Sequence[Interval], detected: Sequence[Interval], min_coverage: float = 0.5
) -> float | None:
    """Fração dos trechos `farm` cobertos em pelo menos `min_coverage` por rotinas detectadas."""
    if not expected:
        return None
    hit = 0
    for exp in expected:
        length = exp[1] - exp[0]
        covered = sum(overlap(exp, d) for d in _merge(detected))
        if length > 0 and covered / length >= min_coverage:
            hit += 1
    return hit / len(expected)


def _merge(intervals: Sequence[Interval]) -> list[Interval]:
    merged: list[Interval] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


@dataclass(frozen=True)
class Utterance:
    start_frame: int
    end_frame: int
    text: str


@dataclass(frozen=True)
class QualityReport:
    wer: float | None
    wer_words: int
    detection: dict[str, Detection]
    false_per_10_min: dict[str, float]
    routine_recall: float | None


def evaluate(
    annotations: Sequence[Annotation],
    utterances: Sequence[Utterance],
    events: Sequence[tuple[str, Interval]],
    routines: Sequence[Interval],
    total_frames: int,
    tolerance_s: float = 1.0,
) -> QualityReport:
    """Compara as saídas da análise com o gabarito.

    WER: para cada `fala` anotada, junta o texto transcrito que cai nela e compara com a `nota`;
    o WER final é o total de erros sobre o total de palavras de referência (não a média dos WERs).
    """
    tolerance = round(tolerance_s * FPS)
    errors = words = 0
    for ann in annotations:
        if ann.cls != "fala" or not ann.note:
            continue
        ref_words = len(normalize_text(ann.note))
        heard = " ".join(
            u.text
            for u in utterances
            if overlap((u.start_frame, u.end_frame), (ann.start_frame, ann.end_frame)) > 0
        )
        rate = wer(ann.note, heard)
        if rate is not None:
            errors += round(rate * ref_words)
            words += ref_words

    def spans(cls: str) -> list[Interval]:
        return [(a.start_frame, a.end_frame) for a in annotations if a.cls == cls]

    detection = {
        cls: match_events(spans(cls), [iv for kind, iv in events if kind == cls], tolerance)
        for cls in ("risada", "grito")
    }
    spoken = spans("fala")
    # Texto do Whisper onde não há fala anotada também é falso positivo (ruído de boca virando palavra).
    ghost_speech = [
        (u.start_frame, u.end_frame)
        for u in utterances
        if not any(overlap((u.start_frame, u.end_frame), s) > 0 for s in spoken)
    ]
    all_events = [iv for _, iv in events] + ghost_speech
    false_rates = {
        cls: false_events_per_10_min(spans(cls), all_events, total_frames)
        for cls in ("teclado", "respiracao")
    }
    return QualityReport(
        wer=errors / words if words else None,
        wer_words=words,
        detection=detection,
        false_per_10_min=false_rates,
        routine_recall=routine_recall(spans("farm"), routines),
    )


def render(report: QualityReport) -> str:
    def pct(value: float | None) -> str:
        return "n/a" if value is None else f"{value * 100:.1f}%"

    lines = [f"WER: {pct(report.wer)} ({report.wer_words} palavras de referência)"]
    for cls, det in report.detection.items():
        lines.append(
            f"{cls}: precisão {pct(det.precision)}, revocação {pct(det.recall)} "
            f"({det.true_positives}/{det.expected} esperados, {det.predicted} previstos)"
        )
    for cls, rate in report.false_per_10_min.items():
        lines.append(f"{cls}: {rate:.2f} eventos falsos por 10 min")
    lines.append(f"rotina (farm): revocação {pct(report.routine_recall)}")
    return "\n".join(lines)
