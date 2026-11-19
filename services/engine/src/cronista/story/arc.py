"""Estrutura narrativa (Fase 5): capítulos, beats e alocação de tempo, a partir dos segmentos da Fase 4.

Regras puras e explicáveis. Capítulo = trecho entre dois `novo_dia` (o número do dia sai na edição).
Beats (plano 5.4): setup → conflito → falha → virada → conquista; conflito e falha são o "sofrimento".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from cronista.relevance.engine import RelevanceParams, Segment, is_kept, kept_seconds
from cronista.story.models import Beat, Span

MIN_CHAPTER_S = 30.0
SETUP_FRACTION = 0.2


@dataclass
class BeatedSegment:
    span: Span
    segment: Segment
    beat: Beat
    marker_kinds: list[str] = field(default_factory=list)
    keep_score: float = RelevanceParams.keep_score

    @property
    def product_s(self) -> float:
        return kept_seconds(self.segment, self.keep_score)


@dataclass
class Chapter:
    number: int
    items: list[BeatedSegment] = field(default_factory=list)
    allocated_s: float = 0.0

    @property
    def product_s(self) -> float:
        return sum(i.product_s for i in self.items)


def build_chapters(
    files: Sequence[tuple[int, Sequence[Segment]]],
    marker_kinds: Mapping[str, str],
    keep_score: float = RelevanceParams.keep_score,
) -> list[Chapter]:
    """`files`: `(file_id, segmentos)` na ordem da sessão. Um `novo_dia` abre um capítulo novo."""
    chapters: list[Chapter] = [Chapter(1)]
    for file_id, segments in files:
        for seg in sorted(segments, key=lambda s: s.start_s):
            kinds = sorted({marker_kinds[m] for m in seg.markers if m in marker_kinds})
            if "novo_dia" in kinds and chapters[-1].items:
                chapters.append(Chapter(len(chapters) + 1))
            if not is_kept(seg, keep_score):
                continue
            chapters[-1].items.append(
                BeatedSegment(
                    Span(file_id=file_id, start_s=seg.start_s, end_s=seg.end_s),
                    seg,
                    Beat.CONFLITO,
                    kinds,
                    keep_score,
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
    """Reparte o tempo-alvo do vídeo entre os capítulos, proporcional ao material relevante de cada um.

    O piso `MIN_CHAPTER_S` (que encolhe para `alvo / nº de capítulos` quando não cabe) e o teto (o material
    real do capítulo, histórico §40: não "preencher tempo") entram na conta e o resto é redistribuído, então a
    soma não passa do alvo por causa do piso. Se não há material
    para o alvo, a soma fica abaixo dele.
    """
    if not chapters:
        return
    floor = min(
        MIN_CHAPTER_S, target_s / len(chapters)
    )  # com capítulos demais o piso encolhe: o alvo vale mais
    fixed: dict[int, float] = {}
    while True:
        free = [n for n in range(len(chapters)) if n not in fixed]
        if not free:
            break
        remaining = target_s - sum(fixed.values())
        weight = sum(chapters[n].product_s for n in free)
        share = {n: remaining * (chapters[n].product_s / weight if weight else 1 / len(free)) for n in free}
        below = [n for n in free if share[n] < min(floor, chapters[n].product_s)]
        if below:
            fixed.update({n: min(floor, chapters[n].product_s) for n in below})
            continue
        above = [n for n in free if share[n] > chapters[n].product_s]
        if above:
            fixed.update({n: chapters[n].product_s for n in above})
            continue
        fixed.update(share)
        break
    for n, c in enumerate(chapters):
        c.allocated_s = round(fixed[n], 1)


def arc_complete(chapters: Sequence[Chapter]) -> bool:
    """Arco completo (§40): começo (setup), meio (conflito/falha) e fim com clímax (virada/conquista)."""
    beats = {item.beat for chapter in chapters for item in chapter.items}
    return (
        Beat.SETUP in beats
        and bool(beats & {Beat.CONFLITO, Beat.FALHA})
        and bool(beats & {Beat.VIRADA, Beat.CONQUISTA})
    )
