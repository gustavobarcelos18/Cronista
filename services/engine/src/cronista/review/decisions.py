"""Decisões do criador sobre segmentos (Fase 7C): tabela só de inserção, a última linha vale."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.db.models import SegmentDecision
from cronista.relevance.engine import Segment
from cronista.relevance.service import load_segments

Decision = Literal["aceito", "rejeitado", "ajustado"]


def record_decision(
    db: Session,
    media_id: int,
    seg_start_s: int,
    decision: Decision,
    start_s: float | None = None,
    end_s: float | None = None,
    *,
    seg_end_s: int | None = None,
    duration_s: float | None = None,
) -> SegmentDecision:
    """Grava a decisão. `seg_end_s` prende a decisão à janela do segmento: se a relevância for recalculada
    e a janela mudar, a decisão deixa de valer (sem ele, vale só pelo início, como antes).

    No ajuste, o fim não pode passar da duração do arquivo (`duration_s`) nem invadir outro segmento.
    """
    if decision == "ajustado":
        if start_s is None or end_s is None or not (math.isfinite(start_s) and math.isfinite(end_s)):
            raise ValueError("ajuste precisa de início e fim finitos em segundos")
        if end_s <= start_s or start_s < 0:
            raise ValueError("ajuste precisa de início e fim válidos (fim depois do início)")
        if duration_s is not None and max(end_s, round(end_s)) > duration_s:
            raise ValueError(f"o fim ({end_s:.0f} s) passa da duração do arquivo ({duration_s:.0f} s)")
        start_s, end_s = round(start_s), round(end_s)
        if end_s <= start_s:
            raise ValueError("o ajuste precisa ter ao menos um segundo após o arredondamento")
        for other in _effective_with_origin(db, media_id):
            if other[0] != seg_start_s and start_s < other[1].end_s and end_s > other[1].start_s:
                raise ValueError(
                    f"o ajuste invade o segmento de {other[1].start_s} a {other[1].end_s} s; ajuste-o"
                )
    else:
        start_s = end_s = None
    previous = current_decisions(db, media_id).get(seg_start_s)
    row = SegmentDecision(
        media_file_id=media_id,
        seg_start_s=seg_start_s,
        seg_end_s=seg_end_s,
        decision=decision,
        start_s=start_s,
        end_s=end_s,
        replaces_id=previous.id if previous else None,
    )
    db.add(row)
    db.commit()
    return row


def current_decisions(db: Session, media_id: int) -> dict[int, SegmentDecision]:
    """Decisão vigente por segmento (a última inserida)."""
    rows = db.scalars(
        select(SegmentDecision).where(SegmentDecision.media_file_id == media_id).order_by(SegmentDecision.id)
    )
    return {r.seg_start_s: r for r in rows}


def decision_for(decisions: dict[int, SegmentDecision], seg: Segment) -> SegmentDecision | None:
    """Decisão vigente do segmento, só se foi tomada para esta janela (início e fim) do segmento."""
    d = decisions.get(seg.start_s)
    if d is None or (d.seg_end_s is not None and d.seg_end_s != seg.end_s):
        return None
    return d


def _effective_with_origin(db: Session, media_id: int) -> list[tuple[int, Segment]]:
    """`(início original, segmento efetivo)`: o início original identifica a decisão mesmo após o ajuste."""
    decisions = current_decisions(db, media_id)
    out: list[tuple[int, Segment]] = []
    for seg in load_segments(db, media_id):
        d = decision_for(decisions, seg)
        if d is None or d.decision == "aceito":
            out.append((seg.start_s, seg))
        elif d.decision == "ajustado" and d.start_s is not None and d.end_s is not None:
            start, end = round(d.start_s), round(d.end_s)
            if end > start:
                out.append((seg.start_s, replace(seg, start_s=start, end_s=end)))
    return out


def load_effective_segments(db: Session, media_id: int) -> list[Segment]:
    """Segmentos da relevância com as decisões do criador aplicadas (usado por roteiro, montagem e Shorts).

    `rejeitado` tira o trecho; `ajustado` troca os limites (ao segundo); `aceito` e sem decisão ficam.
    Decisão tomada para outra janela do segmento (relevância recalculada) é ignorada.
    """
    return sorted((seg for _, seg in _effective_with_origin(db, media_id)), key=lambda s: s.start_s)
