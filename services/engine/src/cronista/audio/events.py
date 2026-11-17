"""Persistência dos eventos de análise na tabela `event`."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from cronista.db.models import Event
from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource
from cronista.domain.models import StageResult


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


@dataclass(frozen=True)
class StoredEvent:
    """Evento lido do banco, com a execução (etapa + variante) que o produziu."""

    stage: str
    variant: str
    event: AnalysisEvent

    @property
    def producer(self) -> str:
        return f"{self.stage}:{self.variant}" if self.variant else self.stage


def load_stored_events(
    db: Session,
    media_file_id: int,
    *,
    kind: str | None = None,
    stage: str | None = None,
    variant: str | None = None,
    start_frame: int | None = None,
    end_frame: int | None = None,
) -> list[StoredEvent]:
    """Eventos de um arquivo em ordem de tempo; `start_frame`/`end_frame` filtram a janela `[inicio, fim)`.

    Um evento entra se tem algum quadro dentro da janela. Evento pontual (`start == end`) conta como o
    quadro em que está: um no primeiro quadro da janela entra, um no quadro `end_frame` não.
    """
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
        query = query.where(or_(Event.end_frame > start_frame, Event.start_frame >= start_frame))
    rows = db.scalars(query.order_by(Event.start_frame, Event.id))
    return [
        StoredEvent(
            stage=row.stage,
            variant=row.variant,
            event=AnalysisEvent(
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
            ),
        )
        for row in rows
    ]


def load_events(db: Session, media_file_id: int, **filters: Any) -> list[AnalysisEvent]:
    """Como `load_stored_events`, só com os eventos (sem dizer quem os produziu)."""
    return [stored.event for stored in load_stored_events(db, media_file_id, **filters)]


EVENTS_KEY = "events"
"""Chave em `StageResult.data` com o caminho do `events.json` de uma etapa que produz eventos."""

_EVENT_LIST = TypeAdapter(list[AnalysisEvent])


def write_events_file(out_dir: Path, events: Sequence[AnalysisEvent]) -> str:
    """Grava os eventos de uma etapa em `events.json` (a etapa é pura: o banco é atualizado depois)."""
    path = out_dir / "events.json"
    path.write_bytes(_EVENT_LIST.dump_json(list(events), indent=1))
    return str(path)


def events_from_result(result: StageResult) -> list[AnalysisEvent] | None:
    """Eventos produzidos por uma etapa, ou `None` se ela não produz eventos."""
    path = result.data.get(EVENTS_KEY)
    if not path:
        return None
    return _EVENT_LIST.validate_json(Path(str(path)).read_bytes())
