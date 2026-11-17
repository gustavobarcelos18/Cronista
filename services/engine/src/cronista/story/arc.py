"""Estrutura narrativa (Fase 5): capítulos, beats e alocação de tempo, a partir dos segmentos da Fase 4.

Regras puras e explicáveis. Capítulo = trecho entre dois `novo_dia` (o número do dia sai na edição).
Beats (plano 5.4): setup → conflito → falha → virada → conquista; conflito e falha são o "sofrimento".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from cronista.relevance.engine import Segment
from cronista.relevance.service import MAX_FARM_S, MAX_KEPT_S, TIMELAPSE_FACTOR
from cronista.story.models import Beat, Span

KEEP_SCORE = 0.35
MIN_CHAPTER_S = 30.0
SETUP_FRACTION = 0.2


@dataclass
class BeatedSegment:
    span: Span
    segment: Segment
    beat: Beat
    marker_kinds: list[str] = field(default_factory=list)

    @property
    def product_s(self) -> float:
        s = self.segment
        if s.classe == "farm":
            return min(s.duration_s / TIMELAPSE_FACTOR, MAX_FARM_S)
        return min(float(s.duration_s), MAX_KEPT_S)


@dataclass
class Chapter:
    number: int
    items: list[BeatedSegment] = field(default_factory=list)
    allocated_s: float = 0.0

    @property
    def product_s(self) -> float:
        return sum(i.product_s for i in self.items)


def is_kept(seg: Segment) -> bool:
    if seg.classe == "descartavel":
        return False
    return seg.classe in ("farm", "dia") or seg.score >= KEEP_SCORE or bool(seg.markers)


def build_chapters(
    files: Sequence[tuple[int, Sequence[Segment]]], marker_kinds: Mapping[str, str]
) -> list[Chapter]:
    """`files`: `(file_id, segmentos)` na ordem da sessão. Um `novo_dia` abre um capítulo novo."""
    chapters: list[Chapter] = [Chapter(1)]
    for file_id, segments in files:
        for seg in sorted(segments, key=lambda s: s.start_s):
            kinds = sorted({marker_kinds[m] for m in seg.markers if m in marker_kinds})
            if "novo_dia" in kinds and chapters[-1].items:
                chapters.append(Chapter(len(chapters) + 1))
            if not is_kept(seg):
                continue
            chapters[-1].items.append(
                BeatedSegment(
                    Span(file_id=file_id, start_s=seg.start_s, end_s=seg.end_s), seg, Beat.CONFLITO, kinds
                )
            )
    chapters = [c for c in chapters if c.items]
    for number, chapter in enumerate(chapters, start=1):
        chapter.number = number
        assign_beats(chapter)
    return chapters


def assign_beats(chapter: Chapter) -> None:
    """Falha e conquista vêm dos marcadores; a virada é o primeiro trecho forte depois de uma falha."""
    total = chapter.product_s or 1.0
    acc = 0.0
    failed = False
    for item in chapter.items:
        kinds = item.marker_kinds
        if "morte_falha" in kinds:
            item.beat, failed = Beat.FALHA, True
        elif "conquista" in kinds:
            item.beat, failed = Beat.CONQUISTA, False
        elif failed and (item.segment.score >= 0.5 or item.segment.features.get("emocao", 0.0) >= 0.2):
            item.beat, failed = Beat.VIRADA, False
        elif acc / total < SETUP_FRACTION and not kinds:
            item.beat = Beat.SETUP
        else:
            item.beat = Beat.CONFLITO
        acc += item.product_s


def allocate_time(chapters: Sequence[Chapter], target_s: float) -> None:
    """Reparte o tempo-alvo do vídeo entre os capítulos, proporcional ao material relevante de cada um."""
    total = sum(c.product_s for c in chapters)
    if not chapters:
        return
    for c in chapters:
        share = c.product_s / total if total else 1 / len(chapters)
        c.allocated_s = round(max(MIN_CHAPTER_S, share * target_s), 1)
