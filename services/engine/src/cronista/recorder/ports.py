"""Portas do gravador: tudo que toca o mundo de fora (OBS, teclado, som) fica atrás de uma interface.

Assim o núcleo (`core.Recorder`) é testado sem OBS, sem teclado e sem alto-falante, e as bibliotecas
(simpleobsws, pynput) podem ser trocadas se perderem manutenção.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from cronista.domain.models import MarkerKind
from cronista.ingest.journal import Stamp

Clock = Callable[[], Stamp]

STATE_STARTED = "OBS_WEBSOCKET_OUTPUT_STARTED"
STATE_STOPPED = "OBS_WEBSOCKET_OUTPUT_STOPPED"
STATE_PAUSED = "OBS_WEBSOCKET_OUTPUT_PAUSED"
STATE_RESUMED = "OBS_WEBSOCKET_OUTPUT_RESUMED"


class ObsError(Exception):
    """Falha de conexão ou de requisição ao OBS."""


@dataclass(frozen=True)
class RecordState:
    """`RecordStateChanged`. `output_path` só vem ao parar (protocolo 5.x), nunca ao iniciar."""

    state: str
    output_path: str | None
    stamp: Stamp


@dataclass(frozen=True)
class RecordFile:
    """`RecordFileChanged` (obs-websocket 5.5+): o OBS dividiu a gravação e começou outro arquivo."""

    new_path: str
    stamp: Stamp


ObsEvent = RecordState | RecordFile


@dataclass(frozen=True)
class RecordStatus:
    active: bool
    paused: bool
    duration_s: float


class ObsLink(Protocol):
    async def connect(self) -> None: ...

    async def next_event(self) -> ObsEvent | None:
        """Próximo evento de gravação, na ordem de chegada; None quando a conexão caiu."""
        ...

    async def record_status(self) -> RecordStatus: ...

    async def record_directory(self) -> str: ...

    async def create_chapter(self, name: str) -> bool:
        """Cria o marcador (capítulo) no arquivo em gravação. False se o OBS recusou."""
        ...

    async def close(self) -> None: ...


class Feedback(Protocol):
    def marked(self, kind: MarkerKind, detail: str = "") -> None:
        """Toque registrado (som/mensagem discreta: é como o criador sabe que funcionou)."""
        ...

    def warn(self, message: str) -> None: ...

    def info(self, message: str) -> None: ...


class HotkeySource(Protocol):
    def start(self, on_press: Callable[[MarkerKind], None]) -> None:
        """Começa a escutar. `on_press` pode ser chamado de qualquer thread."""
        ...

    def stop(self) -> None: ...
