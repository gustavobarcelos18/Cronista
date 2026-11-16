"""Núcleo do gravador: transforma eventos do OBS e toques de tecla em diário + marcador no arquivo.

A cada toque, nesta ordem: (1) linha no diário com o instante do toque; (2) marcador `tipo|id` no arquivo
do OBS (`CreateRecordChapter`); (3) feedback. Os dois registros são independentes: se o OBS recusar o
marcador, o diário ainda tem o toque, e a ingestão reconcilia (plano mestre, seção 4).
"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cronista.config import Settings
from cronista.domain.journal import FileChanged, RecordingStarted, RecordingStopped, chapter_title
from cronista.domain.models import MarkerKind
from cronista.domain.timeline import file_key
from cronista.ingest.journal import JOURNAL_SUFFIX, JournalWriter, Stamp, find_journals, read_journal
from cronista.logging_setup import log_event
from cronista.recorder.files import find_recording_file, utc_stamp_name
from cronista.recorder.ports import (
    STATE_PAUSED,
    STATE_RESUMED,
    STATE_STARTED,
    STATE_STOPPED,
    Clock,
    Feedback,
    ObsError,
    ObsEvent,
    ObsLink,
    RecordFile,
    RecordState,
)


def system_clock() -> Stamp:
    return Stamp(time.monotonic(), datetime.now(UTC))


def new_marker_id() -> str:
    return secrets.token_hex(4)


class Recorder:
    def __init__(
        self,
        obs: ObsLink,
        feedback: Feedback,
        settings: Settings,
        *,
        clock: Clock = system_clock,
        new_id: Callable[[], str] = new_marker_id,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        find_timeout_s: float = 3.0,
    ) -> None:
        self._obs, self._feedback, self._settings = obs, feedback, settings
        self._clock, self._new_id, self._sleep = clock, new_id, sleep
        self._find_timeout_s = find_timeout_s
        self._recording = False
        self._journal: JournalWriter | None = None
        self._ready = asyncio.Event()  # diário aberto (ou impossível); toques esperam por ele
        self._construction_open = False
        self._count = 0

    # --- estado (leitura) ---

    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def construction_open(self) -> bool:
        return self._construction_open

    # --- eventos do OBS ---

    async def attach(self) -> None:
        """Ao conectar: se o OBS já está gravando (o gravador abriu depois, ou caiu), assume a gravação."""
        status = await self._obs.record_status()
        if not status.active or self._recording:
            return
        now = self._clock()
        started = Stamp(now.mono_s - status.duration_s, now.utc - timedelta(seconds=status.duration_s))
        self._feedback.warn(
            "OBS já estava gravando: o início é estimado pela duração e pausas anteriores não constam"
        )
        await self._begin(started, adopted=True)
        if status.paused and self._journal is not None:
            self._journal.paused(now)

    async def handle(self, event: ObsEvent) -> None:
        match event:
            case RecordState(state=state, stamp=stamp):
                if state == STATE_STARTED and not self._recording:
                    await self._begin(stamp)
                elif state == STATE_STOPPED and self._recording:
                    self._end(stamp)
                elif state == STATE_PAUSED and self._journal is not None:
                    self._journal.paused(stamp)
                elif state == STATE_RESUMED and self._journal is not None:
                    self._journal.unpaused(stamp)
            case RecordFile(new_path=path, stamp=stamp):
                if self._journal is not None:
                    self._journal.file_changed(path, stamp)
                    log_event("arquivo_dividido", path=path)

    async def _begin(self, stamp: Stamp, *, adopted: bool = False) -> None:
        self._recording, self._construction_open, self._count = True, False, 0
        self._ready.clear()
        try:
            directory = Path(await self._obs.record_directory())
        except ObsError as exc:
            self._feedback.warn(f"sem a pasta de gravação do OBS ({exc}): toques só no marcador do OBS")
            self._ready.set()
            return

        path = await find_recording_file(
            directory,
            self._settings.video_extensions,
            stamp.utc,
            timeout_s=self._find_timeout_s,
            sleep=self._sleep,
        )
        if path is None:
            self._feedback.warn(
                f"não achei o arquivo da gravação em {directory}: a ingestão vai assumir o primeiro arquivo"
            )

        journal_path = _open_journal(directory, path) if adopted else None
        if journal_path is not None:
            self._journal = JournalWriter(journal_path)
            self._feedback.warn(f"diário retomado ({journal_path.name}); o que passou fora do ar não consta")
        else:
            self._journal = JournalWriter(directory / f"{utc_stamp_name(stamp.utc)}{JOURNAL_SUFFIX}")
            self._journal.recording_started(str(path) if path else "", stamp)
        self._feedback.info(f"Gravando: {path.name if path else '(arquivo desconhecido)'}")
        log_event("gravacao_iniciada", path=str(path) if path else None, adotada=adopted)
        self._ready.set()

    def _end(self, stamp: Stamp) -> None:
        if self._journal is not None:
            self._journal.recording_stopped(stamp)
            self._journal.close()
            self._journal = None
        if self._construction_open:
            self._feedback.warn("construção ficou aberta: a ingestão fecha no fim da sessão, com aviso")
        self._feedback.info(f"Gravação encerrada: {self._count} marcador(es)")
        log_event("gravacao_encerrada", marcadores=self._count)
        self._recording, self._construction_open = False, False
        self._ready.clear()

    # --- toques ---

    async def press(self, kind: MarkerKind, stamp: Stamp) -> None:
        """Um toque. `stamp` é o instante em que a tecla foi apertada, não o de agora."""
        if not self._recording:
            self._feedback.warn(f"{kind.value}: fora de gravação, ignorado")
            return
        await self._ready.wait()
        if not self._recording:  # a gravação acabou enquanto esperava
            self._feedback.warn(f"{kind.value}: fora de gravação, ignorado")
            return

        marker_id = self._new_id()
        if self._journal is not None:
            self._journal.marker(kind, marker_id, stamp)
        self._count += 1
        detail = ""
        if kind is MarkerKind.CONSTRUCAO:
            self._construction_open = not self._construction_open
            detail = "início" if self._construction_open else "fim"

        created = False
        try:
            created = await self._obs.create_chapter(chapter_title(kind, marker_id))
        except ObsError as exc:
            self._feedback.warn(f"{kind.value}: {exc}")
        if self._journal is None:
            self._feedback.warn(f"{kind.value}: sem diário; só o marcador do OBS registrou o toque")
        elif not created:
            self._feedback.warn(f"{kind.value}: o OBS não criou o marcador no arquivo; o diário tem o toque")
        self._feedback.marked(kind, detail)
        log_event("marcador", kind=kind.value, marker_id=marker_id, no_arquivo=created)

    def close(self) -> None:
        """Encerra o gravador sem fechar a gravação: o OBS continua gravando e a retomada reabre o diário."""
        if self._journal is not None:
            self._journal.close()
            self._journal = None


def _open_journal(directory: Path, current_file: Path | None) -> Path | None:
    """Diário de uma gravação em andamento (gravador reiniciado): o último sem `recording_stopped`."""
    if current_file is None:
        return None
    for candidate in reversed(find_journals(directory)):
        events, _ = read_journal(candidate)
        files = [e.path for e in events if isinstance(e, RecordingStarted | FileChanged)]
        stopped = bool(events) and isinstance(events[-1], RecordingStopped)
        if files and not stopped and file_key(files[-1]) == file_key(str(current_file)):
            return candidate
    return None
