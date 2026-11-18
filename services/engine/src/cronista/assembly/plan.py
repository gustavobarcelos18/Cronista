"""Plano de montagem (Fase 6A): capítulos da Fase 5 → lista de cortes em quadros inteiros a 60 fps.

Puro e determinístico (mesma entrada, mesmo plano): não lê banco nem roda FFmpeg. Regras (plano 6.3):
folga de 1 a 2 s, corte nunca dentro de palavra, orçamento de tempo por capítulo (cai primeiro o que tem
menor nota; falha, virada, conquista e trechos com marcador são protegidos), trecho de farm vira timelapse,
trecho longo vira montagem (mantém o desfecho), B-roll em V3 e cartela de capítulo em V5 (sem número de dia).
"""

from __future__ import annotations

import bisect
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from typing import Any

from cronista.domain.frames import FPS
from cronista.relevance.service import MAX_FARM_S, MAX_KEPT_S
from cronista.story.arc import BeatedSegment, Chapter
from cronista.story.models import Beat

PROTECTED_BEATS = frozenset({Beat.FALHA, Beat.VIRADA, Beat.CONQUISTA})


class Mode(StrEnum):
    AO_VIVO = "ao_vivo"
    MONTAGEM = "montagem"
    TIMELAPSE = "timelapse"
    BROLL = "broll"


LIVE_MODES = frozenset({Mode.AO_VIVO, Mode.MONTAGEM})
"""Cortes de gameplay ao vivo: os únicos que recebem zoom e shake (V2) e que o acabamento anima."""


class Track(StrEnum):
    V1 = "V1"
    V3 = "V3"
    V5 = "V5"


@dataclass(frozen=True)
class AssemblyParams:
    pad_s: float = 1.5
    """Folga antes e depois do trecho (plano: 1 a 2 s)."""
    min_clip_s: float = 1.0
    max_kept_s: float = MAX_KEPT_S
    max_farm_s: float = MAX_FARM_S
    timelapse_min: int = 4
    timelapse_max: int = 50
    broll_per_chapter: int = 1
    broll_max_s: float = 6.0
    card_s: float = 3.0
    word_snap_s: float = 1.0
    """Quanto o corte pode andar para sair de dentro de uma palavra."""


@dataclass(frozen=True)
class WordSpan:
    start_frame: int
    end_frame: int


@dataclass(frozen=True)
class BrollClip:
    file_id: int
    start_frame: int
    end_frame: int
    confidence: float
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class EditItem:
    """Um corte: `[in_frame, out_frame)` do arquivo, posto na timeline em `timeline_start` (quadros)."""

    file_id: int
    in_frame: int
    out_frame: int
    track: Track
    mode: Mode
    speed: int
    reason: str
    chapter: int
    beat: str
    segment_id: str
    score: float
    protected: bool = False
    timeline_start: int = 0

    @property
    def source_frames(self) -> int:
        return self.out_frame - self.in_frame

    @property
    def timeline_frames(self) -> int:
        return max(1, round(self.source_frames / self.speed))

    @property
    def timeline_end(self) -> int:
        return self.timeline_start + self.timeline_frames


@dataclass(frozen=True)
class Card:
    """Cartela de capítulo (V5). Sem número: o "Dia N" é decidido na edição (plano, seção 4)."""

    chapter: int
    timeline_start: int
    frames: int
    text: str
    editable_number: bool = True


@dataclass
class EditPlan:
    items: list[EditItem] = field(default_factory=list)
    cards: list[Card] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    chapter_budget_s: dict[int, float] = field(default_factory=dict)

    @property
    def v1(self) -> list[EditItem]:
        return [i for i in self.items if i.track == Track.V1]

    @property
    def total_frames(self) -> int:
        v1 = self.v1
        return v1[-1].timeline_end if v1 else 0

    @property
    def total_s(self) -> float:
        return self.total_frames / FPS

    def chapter_s(self, chapter: int) -> float:
        return sum(i.timeline_frames for i in self.v1 if i.chapter == chapter) / FPS

    def to_json(self) -> str:
        data: dict[str, Any] = {
            "fps": FPS,
            "total_frames": self.total_frames,
            "orcamento_s": {str(k): v for k, v in self.chapter_budget_s.items()},
            "itens": [asdict(i) for i in self.items],
            "cartelas": [asdict(c) for c in self.cards],
            "avisos": self.warnings,
        }
        return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)


def _frames(seconds: float) -> int:
    return round(seconds * FPS)


def snap_out_of_words(frame: int, words: Sequence[WordSpan], limit: int, *, move_to: str) -> int:
    """Tira o corte de dentro de uma palavra: `start` leva ao começo dela, `end` ao fim (até `limit` quadros).

    Se a palavra for longa demais para o limite, o corte fica onde está.
    """
    starts = [w.start_frame for w in words]
    idx = bisect.bisect_left(starts, frame) - 1
    if idx < 0:
        return frame
    word = words[idx]
    if not (word.start_frame < frame < word.end_frame):
        return frame
    target = word.start_frame if move_to == "start" else word.end_frame
    return target if abs(target - frame) <= limit else frame


def _draft(
    seg: BeatedSegment,
    chapter: int,
    words: Sequence[WordSpan],
    duration_frames: int | None,
    params: AssemblyParams,
) -> EditItem:
    s = seg.segment
    start, end = _frames(seg.span.start_s), _frames(seg.span.end_s)
    speed, mode = 1, Mode.AO_VIVO
    reason = ", ".join(s.razoes[:3]) or s.classe
    if s.classe == "farm":
        mode = Mode.TIMELAPSE
        speed = min(
            params.timelapse_max,
            max(params.timelapse_min, math.ceil((end - start) / FPS / params.max_farm_s)),
        )
        reason = f"farm repetitivo em {speed}x"
    else:
        pad = _frames(params.pad_s)
        start, end = start - pad, end + pad
        if (end - start) / FPS > params.max_kept_s:
            mode = Mode.MONTAGEM
            start = end - _frames(params.max_kept_s)  # mantém o desfecho (o marcador fica no fim do trecho)
            reason = f"trecho longo resumido ao desfecho; {reason}"
        limit = _frames(params.word_snap_s)
        start = snap_out_of_words(start, words, limit, move_to="start")
        end = snap_out_of_words(end, words, limit, move_to="end")
    start = max(0, start)
    if duration_frames is not None:
        end = min(end, duration_frames)
    return EditItem(
        file_id=seg.span.file_id,
        in_frame=start,
        out_frame=max(start, end),
        track=Track.V1,
        mode=mode,
        speed=speed,
        reason=reason,
        chapter=chapter,
        beat=seg.beat.value,
        segment_id=seg.span.segment_id,
        score=s.score,
        protected=seg.beat in PROTECTED_BEATS or bool(s.markers),
    )


def fit_budget(items: list[EditItem], budget_s: float) -> tuple[list[EditItem], float]:
    """Tira os trechos de menor nota (os últimos primeiro, em empate) até caber; protegidos nunca saem.

    Devolve os itens que ficaram (na ordem original) e quanto ainda passa do orçamento (0 se coube).
    """
    budget_frames = _frames(budget_s)
    kept = list(items)

    def total() -> int:
        return sum(i.timeline_frames for i in kept)

    while total() > budget_frames:
        droppable = [(n, i) for n, i in enumerate(kept) if not i.protected]
        if not droppable:
            break
        n, _ = min(droppable, key=lambda p: (p[1].score, -p[0]))
        kept.pop(n)
    return kept, max(0.0, (total() - budget_frames) / FPS)


def _merge_and_clip(items: list[EditItem], min_frames: int) -> list[EditItem]:
    """Funde trechos vizinhos do mesmo arquivo que se tocam; evita o mesmo quadro duas vezes."""
    out: list[EditItem] = []
    for item in items:
        prev = out[-1] if out else None
        if prev is not None and prev.file_id == item.file_id and item.in_frame < prev.out_frame:
            if prev.speed == 1 and item.speed == 1:
                out[-1] = replace(
                    prev,
                    out_frame=max(prev.out_frame, item.out_frame),
                    reason=f"{prev.reason}; {item.reason}",
                    score=max(prev.score, item.score),
                    protected=prev.protected or item.protected,
                    beat=item.beat if (item.protected and not prev.protected) else prev.beat,
                )
                continue
            item = replace(item, in_frame=prev.out_frame)
        if item.source_frames >= min_frames:
            out.append(item)
    return out


def _place_broll(
    plan: EditPlan, broll: Mapping[int, Sequence[BrollClip]], params: AssemblyParams
) -> list[EditItem]:
    """Um cutaway por capítulo (até `broll_per_chapter`), no começo do primeiro trecho de V1 que o comporta,
    sempre de outro momento do mesmo arquivo (nunca o que já está em V1 ali)."""
    placed: list[EditItem] = []
    max_frames = _frames(params.broll_max_s)
    for chapter in sorted({i.chapter for i in plan.v1}):
        host = [i for i in plan.v1 if i.chapter == chapter and i.speed == 1]
        used = 0
        for h in host:
            if used >= params.broll_per_chapter:
                break
            options = [
                c
                for c in broll.get(h.file_id, ())
                if (c.end_frame <= h.in_frame or c.start_frame >= h.out_frame)
                and c.end_frame - c.start_frame >= _frames(params.min_clip_s)
            ]
            if not options:
                continue
            best = max(options, key=lambda c: (c.confidence, -c.start_frame))
            length = min(best.end_frame - best.start_frame, max_frames, h.timeline_frames)
            placed.append(
                EditItem(
                    file_id=best.file_id,
                    in_frame=best.start_frame,
                    out_frame=best.start_frame + length,
                    track=Track.V3,
                    mode=Mode.BROLL,
                    speed=1,
                    reason="B-roll: " + (", ".join(best.tags) or "plano de beleza"),
                    chapter=chapter,
                    beat=h.beat,
                    segment_id=h.segment_id,
                    score=best.confidence,
                    timeline_start=h.timeline_start,
                )
            )
            used += 1
    return placed


def build_edit_plan(
    chapters: Sequence[Chapter],
    *,
    words: Mapping[int, Sequence[WordSpan]] | None = None,
    durations: Mapping[int, int] | None = None,
    broll: Mapping[int, Sequence[BrollClip]] | None = None,
    params: AssemblyParams | None = None,
) -> EditPlan:
    """`words` e `durations` (quadros) são por `file_id`; sem eles, não há ajuste de palavra nem limite."""
    p = params or AssemblyParams()
    word_map = {k: sorted(v, key=lambda w: w.start_frame) for k, v in (words or {}).items()}
    plan = EditPlan()
    cursor = 0
    for chapter in chapters:
        drafts = [
            _draft(
                s, chapter.number, word_map.get(s.span.file_id, ()), (durations or {}).get(s.span.file_id), p
            )
            for s in chapter.items
        ]
        drafts = [d for d in drafts if d.source_frames > 0]
        kept, over = fit_budget(drafts, chapter.allocated_s)
        if over > 0:
            plan.warnings.append(
                f"capítulo {chapter.number}: {over:.0f} s acima do orçamento ({chapter.allocated_s:.0f} s),"
                " só com trechos protegidos"
            )
        merged = _merge_and_clip(kept, _frames(p.min_clip_s))
        if not merged:
            plan.warnings.append(f"capítulo {chapter.number}: nenhum trecho utilizável")
            continue
        plan.chapter_budget_s[chapter.number] = chapter.allocated_s
        card_frames = _frames(p.card_s)
        plan.cards.append(Card(chapter.number, cursor, card_frames, f"Capítulo {chapter.number}"))
        for item in merged:
            placed = replace(item, timeline_start=cursor)
            plan.items.append(placed)
            cursor = placed.timeline_end
    plan.items.extend(_place_broll(plan, broll or {}, p))
    return plan
