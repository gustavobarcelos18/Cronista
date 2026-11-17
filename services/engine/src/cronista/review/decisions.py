"""Decisões do criador sobre segmentos (Fase 7C): tabela só de inserção, a última linha vale."""

from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.db.models import SegmentDecision

Decision = Literal["aceito", "rejeitado", "ajustado"]


def record_decision(
    db: Session,
    media_id: int,
    seg_start_s: int,
    decision: Decision,
    start_s: float | None = None,
    end_s: float | None = None,
) -> SegmentDecision:
    if decision == "ajustado":
        if start_s is None or end_s is None or end_s <= start_s or start_s < 0:
            raise ValueError("ajuste precisa de início e fim válidos (fim depois do início)")
    else:
        start_s = end_s = None
    previous = current_decisions(db, media_id).get(seg_start_s)
    row = SegmentDecision(
        media_file_id=media_id,
        seg_start_s=seg_start_s,
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
