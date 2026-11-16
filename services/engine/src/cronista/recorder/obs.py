"""Adaptador real do obs-websocket v5, sobre a `simpleobsws` (mantida pelo autor do protocolo).

Detalhes que valem registro (lidos do código da biblioteca, 1.4.3):
- ela fala o subprotocolo msgpack;
- cada evento vira uma `asyncio.Task` separada, então a ordem só é garantida se o callback apenas enfileira
  (sem `await` antes), que é o que fazemos;
- não avisa quando a conexão cai: vigiamos `ws_open`.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import simpleobsws

from cronista.recorder.ports import Clock, ObsError, ObsEvent, RecordFile, RecordState, RecordStatus

EVENT_SUBSCRIPTION_OUTPUTS = 1 << 6  # `EventSubscription::Outputs` (protocolo 5.x)
WATCH_INTERVAL_S = 0.5


class SimpleObsLink:
    def __init__(
        self,
        host: str,
        port: int,
        password: str | None,
        clock: Clock,
        *,
        identify_timeout_s: float = 10.0,
    ) -> None:
        self._url = f"ws://{host}:{port}"
        self._password = password or ""
        self._clock = clock
        self._identify_timeout_s = identify_timeout_s
        self._ws: Any = None
        self._queue: asyncio.Queue[ObsEvent | None] = asyncio.Queue()
        self._watch_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        ws = simpleobsws.WebSocketClient(
            url=self._url,
            password=self._password,
            identification_parameters=simpleobsws.IdentificationParameters(
                eventSubscriptions=EVENT_SUBSCRIPTION_OUTPUTS
            ),
        )
        ws.register_event_callback(self._on_state, "RecordStateChanged")
        ws.register_event_callback(self._on_file, "RecordFileChanged")
        try:
            await ws.connect()
            identified = await ws.wait_until_identified(timeout=self._identify_timeout_s)
        except OSError as exc:
            raise ObsError(f"não consegui conectar em {self._url}: {exc}") from exc
        if not identified:
            await ws.disconnect()
            raise ObsError(f"o OBS em {self._url} não aceitou a conexão (senha do WebSocket correta?)")
        self._ws = ws
        self._queue = asyncio.Queue()
        self._watch_task = asyncio.create_task(self._watch())

    # Callbacks sem `await` antes do `put_nowait`: a ordem de chegada é a ordem da fila.
    async def _on_state(self, data: dict[str, Any]) -> None:
        self._queue.put_nowait(
            RecordState(str(data.get("outputState", "")), data.get("outputPath"), self._clock())
        )

    async def _on_file(self, data: dict[str, Any]) -> None:
        self._queue.put_nowait(RecordFile(str(data.get("newOutputPath", "")), self._clock()))

    async def _watch(self) -> None:
        while self._ws is not None and self._ws.ws_open:
            await asyncio.sleep(WATCH_INTERVAL_S)
        self._queue.put_nowait(None)

    async def next_event(self) -> ObsEvent | None:
        return await self._queue.get()

    async def _call(self, request_type: str, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if self._ws is None or not self._ws.ws_open:
            raise ObsError("sem conexão com o OBS")
        try:
            response = await self._ws.call(simpleobsws.Request(request_type, data))
        except (simpleobsws.MessageTimeout, simpleobsws.NotIdentifiedError, OSError) as exc:
            raise ObsError(f"{request_type}: {exc}") from exc
        if not response.ok():
            raise ObsError(f"{request_type}: {response.requestStatus.comment or response.requestStatus.code}")
        result: dict[str, Any] | None = response.responseData
        return result

    async def record_status(self) -> RecordStatus:
        data = await self._call("GetRecordStatus") or {}
        return RecordStatus(
            active=bool(data.get("outputActive")),
            paused=bool(data.get("outputPaused")),
            duration_s=float(data.get("outputDuration", 0)) / 1000.0,
        )

    async def record_directory(self) -> str:
        data = await self._call("GetRecordDirectory") or {}
        directory = str(data.get("recordDirectory", ""))
        if not directory:
            raise ObsError("GetRecordDirectory: resposta sem pasta")
        return directory

    async def create_chapter(self, name: str) -> bool:
        try:
            await self._call("CreateRecordChapter", {"chapterName": name})
        except ObsError:
            return False
        return True

    async def close(self) -> None:
        if self._watch_task is not None:
            self._watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watch_task
        if self._ws is not None:
            await self._ws.disconnect()
            self._ws = None
