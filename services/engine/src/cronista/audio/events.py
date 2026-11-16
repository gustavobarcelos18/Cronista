"""Persistência dos eventos de análise na tabela `event`."""

from __future__ import annotations

import json
from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from cronista.db.models import Event
from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource


def replace_events(
    db: Session, media_file_id: int, stage: str, variant: str, events: Iterable[AnalysisEvent]
) -> int:
    """Troca os eventos de uma execução (arquivo + etapa + variante) pelos novos, numa transação só.

    Reexecutar a etapa nunca duplica; eventos de outras variantes e etapas ficam como estão.
    """
    db.execute(
        delete(Event).where(
            Event.media_file_id == media_file_id, Event.stage == stage, Event.variant == variant
        )
    )
    count = 0
    for item in events:
        ev = item.evidence
        db.add(
            Event(
                media_file_id=media_file_id,
                stage=stage,
                variant=variant,
                kind=item.kind,
                start_frame=ev.start_frame,
                end_frame=ev.end_frame,
                source=ev.source.value,
                confidence=ev.confidence,
                model=ev.model,
                model_version=ev.model_version,
                params_hash=ev.params_hash,
                quote=ev.quote,
                payload=json.dumps(item.payload, ensure_ascii=False, sort_keys=True),
            )
        )
        count += 1
    db.commit()
    return count


def load_events(
    db: Session,
    media_file_id: int,
    *,
    kind: str | None = None,
    stage: str | None = None,
    variant: str | None = None,
    start_frame: int | None = None,
    end_frame: int | None = None,
) -> list[AnalysisEvent]:
    """Eventos de um arquivo, em ordem de tempo; `start_frame`/`end_frame` filtram por sobreposição."""
    query = select(Event).where(Event.media_file_id == media_file_id)
    if kind is not None:
        query = query.where(Event.kind == kind)
    if stage is not None:
        query = query.where(Event.stage == stage)
    if variant is not None:
        query = query.where(Event.variant == variant)
    if end_frame is not None:
        query = query.where(Event.start_frame < end_frame)
    if start_frame is not None:
        query = query.where(Event.end_frame > start_frame)
    rows = db.scalars(query.order_by(Event.start_frame, Event.id))
    return [
        AnalysisEvent(
            kind=row.kind,
            evidence=Evidence(
                source=EvidenceSource(row.source),
                start_frame=row.start_frame,
                end_frame=row.end_frame,
                confidence=row.confidence,
                model=row.model,
                model_version=row.model_version,
                params_hash=row.params_hash,
                quote=row.quote,
            ),
            payload=json.loads(row.payload),
        )
        for row in rows
    ]
