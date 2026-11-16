"""Diário de eventos `.markers.jsonl` (plano mestre, seção 4): uma linha JSON por evento.

Cada evento carrega o relógio monotônico (`mono_s`, para somar durações sem sofrer com ajuste de hora) e o
UTC (`utc`, para auditoria). O tempo de mídia de cada marcador é reconstruído a partir deles (ver `timeline`).
Não há número de dia em lugar nenhum.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from cronista.domain.models import MarkerKind


class _Event(BaseModel):
    mono_s: float
    utc: datetime


class RecordingStarted(_Event):
    type: Literal["recording_started"] = "recording_started"
    path: str  # arquivo que o OBS começou a gravar


class Paused(_Event):
    type: Literal["paused"] = "paused"


class Unpaused(_Event):
    type: Literal["unpaused"] = "unpaused"


class FileChanged(_Event):
    type: Literal["file_changed"] = "file_changed"
    path: str  # novo arquivo (divisão automática do OBS)


class RecordingStopped(_Event):
    type: Literal["recording_stopped"] = "recording_stopped"


class MarkerPressed(_Event):
    type: Literal["marker"] = "marker"
    kind: MarkerKind
    marker_id: str


JournalEvent = Annotated[
    RecordingStarted | Paused | Unpaused | FileChanged | RecordingStopped | MarkerPressed,
    Field(discriminator="type"),
]

journal_event_adapter: TypeAdapter[JournalEvent] = TypeAdapter(JournalEvent)

CHAPTER_SEPARATOR = "|"


def chapter_title(kind: MarkerKind, marker_id: str) -> str:
    """Nome do marcador dentro do arquivo do OBS: `tipo|id` (sem número de dia)."""
    return f"{kind.value}{CHAPTER_SEPARATOR}{marker_id}"


def parse_chapter_title(title: str) -> tuple[MarkerKind, str] | None:
    """Inverso de `chapter_title`. Devolve None para títulos que não seguem `tipo|id` (ex.: "Chapter 1")."""
    kind_text, sep, marker_id = title.partition(CHAPTER_SEPARATOR)
    if not sep or not marker_id:
        return None
    try:
        return MarkerKind(kind_text), marker_id
    except ValueError:
        return None
