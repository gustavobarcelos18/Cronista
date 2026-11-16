"""Servidor obs-websocket v5 falso, só o que o gravador usa (subprotocolo msgpack, como a simpleobsws).

Protocolo conforme o doc oficial (obsproject/obs-websocket, protocol.md): Hello(0) → Identify(1) →
Identified(2); Request(6) → RequestResponse(7); Event(5). O `outputPath` de `RecordStateChanged` só vem ao
parar, e `RecordFileChanged` traz `newOutputPath`, como no protocolo real.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import msgpack
from websockets.asyncio.server import ServerConnection, serve

SUBPROTOCOL = "obswebsocket.msgpack"
OUTPUTS = 1 << 6


class FakeObs:
    def __init__(self, record_dir: Path, password: str | None = None) -> None:
        self.record_dir = record_dir
        self.password = password
        self.recording = False
        self.paused = False
        self.duration_ms = 0
        self.chapters: list[str] = []
        self.requests: list[str] = []
        self.fail_chapters = False
        self._connections: list[ServerConnection] = []
        self.port = 0

    # --- protocolo ---

    def _auth_data(self) -> dict[str, str]:
        return {"challenge": "desafio-fake", "salt": "sal-fake"}

    def _expected_auth(self) -> str:
        auth = self._auth_data()
        assert self.password is not None
        secret = base64.b64encode(hashlib.sha256((self.password + auth["salt"]).encode()).digest())
        return base64.b64encode(hashlib.sha256(secret + auth["challenge"].encode()).digest()).decode()

    async def _handle(self, ws: ServerConnection) -> None:
        hello: dict[str, Any] = {"obsWebSocketVersion": "5.5.0", "rpcVersion": 1}
        if self.password is not None:
            hello["authentication"] = self._auth_data()
        await ws.send(msgpack.packb({"op": 0, "d": hello}))

        identify = msgpack.unpackb(await ws.recv())
        if self.password is not None and identify["d"].get("authentication") != self._expected_auth():
            await ws.close(code=4009, reason="Authentication failed.")
            return
        await ws.send(msgpack.packb({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
        self._connections.append(ws)
        try:
            async for raw in ws:
                message = msgpack.unpackb(raw)
                if message["op"] == 6:
                    await ws.send(msgpack.packb({"op": 7, "d": self._respond(message["d"])}))
        finally:
            if ws in self._connections:
                self._connections.remove(ws)

    def _respond(self, request: dict[str, Any]) -> dict[str, Any]:
        kind, data = request["requestType"], request.get("requestData") or {}
        self.requests.append(kind)
        ok: dict[str, Any] = {"result": True, "code": 100}
        body: dict[str, Any] | None = None
        status = ok
        if kind == "GetRecordStatus":
            body = {
                "outputActive": self.recording,
                "outputPaused": self.paused,
                "outputDuration": self.duration_ms,
                "outputBytes": 0,
                "outputTimecode": "00:00:00.000",
            }
        elif kind == "GetRecordDirectory":
            body = {"recordDirectory": str(self.record_dir)}
        elif kind == "CreateRecordChapter":
            if not self.recording or self.fail_chapters:
                status = {"result": False, "code": 501, "comment": "Record output is not active."}
            else:
                self.chapters.append(data.get("chapterName", ""))
        else:
            status = {"result": False, "code": 204, "comment": "Unknown request type."}
        response: dict[str, Any] = {
            "requestType": kind,
            "requestId": request["requestId"],
            "requestStatus": status,
        }
        if body is not None:
            response["responseData"] = body
        return response

    # --- eventos (o que o OBS emitiria) ---

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        payload = {"eventType": event_type, "eventIntent": OUTPUTS, "eventData": data}
        for ws in list(self._connections):
            await ws.send(msgpack.packb({"op": 5, "d": payload}))

    async def start_recording(self) -> None:
        self.recording, self.paused = True, False
        await self.emit(
            "RecordStateChanged",
            {"outputActive": True, "outputState": "OBS_WEBSOCKET_OUTPUT_STARTED", "outputPath": None},
        )

    async def pause(self) -> None:
        self.paused = True
        await self.emit(
            "RecordStateChanged",
            {"outputActive": True, "outputState": "OBS_WEBSOCKET_OUTPUT_PAUSED", "outputPath": None},
        )

    async def resume(self) -> None:
        self.paused = False
        await self.emit(
            "RecordStateChanged",
            {"outputActive": True, "outputState": "OBS_WEBSOCKET_OUTPUT_RESUMED", "outputPath": None},
        )

    async def split(self, new_path: Path) -> None:
        await self.emit("RecordFileChanged", {"newOutputPath": str(new_path)})

    async def stop_recording(self, final_path: Path) -> None:
        self.recording, self.paused = False, False
        await self.emit(
            "RecordStateChanged",
            {
                "outputActive": False,
                "outputState": "OBS_WEBSOCKET_OUTPUT_STOPPED",
                "outputPath": str(final_path),
            },
        )

    async def drop_connections(self) -> None:
        for ws in list(self._connections):
            await ws.close()


@asynccontextmanager
async def running_fake_obs(record_dir: Path, password: str | None = None) -> AsyncIterator[FakeObs]:
    fake = FakeObs(record_dir, password)
    async with serve(fake._handle, "127.0.0.1", 0, subprotocols=[SUBPROTOCOL]) as server:  # type: ignore[list-item]
        fake.port = server.sockets[0].getsockname()[1]
        yield fake
