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
from cronista.domain.journal import (
    FileChanged,
    JournalEvent,
    Paused,
    RecordingStarted,
    RecordingStopped,
    Unpaused,
    chapter_title,
)
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
        self._paused = False
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
        # Reconcilia a pausa: o diário reaberto pode dizer "pausado" (o gravador caiu em pausa e o criador
        # retomou), ou o contrário; sem isto os marcadores seguintes saem presos no ponto da pausa.
        if status.paused and not self._paused:
            self._write("paused", lambda j: j.paused(now))
            self._paused = True
        elif not status.paused and self._paused:
            self._write("unpaused", lambda j: j.unpaused(now))
            self._paused = False

    async def handle(self, event: ObsEvent) -> None:
        match event:
            case RecordState(state=state, stamp=stamp):
                if state == STATE_STARTED and not self._recording:
                    await self._begin(stamp)
                elif state == STATE_STOPPED and self._recording:
                    self._end(stamp)
                elif state == STATE_PAUSED:
                    self._paused = True
                    self._write("paused", lambda j: j.paused(stamp))
                elif state == STATE_RESUMED:
                    self._paused = False
                    self._write("unpaused", lambda j: j.unpaused(stamp))
            case RecordFile(new_path=path, stamp=stamp):
                if self._write("file_changed", lambda j: j.file_changed(path, stamp)):
                    log_event("arquivo_dividido", path=path)

    def _write(self, what: str, action: Callable[[JournalWriter], None]) -> bool:
        """Escreve no diário sem nunca derrubar o gravador: disco cheio ou arquivo bloqueado viram aviso.

        O toque ainda vira marcador no arquivo do OBS; o aviso (com som) diz que o diário falhou.
        """
        if self._journal is None:
            return False
        try:
            action(self._journal)
        except OSError as exc:
            self._feedback.warn(f"diário: não consegui gravar '{what}' ({exc})")
            return False
        return True

    async def _begin(self, stamp: Stamp, *, adopted: bool = False) -> None:
        self._recording, self._construction_open, self._count, self._paused = True, False, 0, False
        self._ready.clear()
        try:
            await self._open(stamp, adopted)
        except (ObsError, OSError) as exc:  # sem pasta, sem permissão, disco cheio...
            self._close_journal()
            self._feedback.warn(f"sem diário nesta gravação ({exc}): toques só no marcador do OBS")
        finally:
            self._ready.set()  # nunca deixa os toques pendurados esperando o diário

    async def _open(self, stamp: Stamp, adopted: bool) -> None:
        directory = Path(await self._obs.record_directory())
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

        reopened = _open_journal(directory, path) if adopted else None
        if reopened is not None:
            journal_path, self._paused = reopened
            self._journal = JournalWriter(journal_path)
            self._feedback.warn(f"diário retomado ({journal_path.name}); o que passou fora do ar não consta")
        else:
            self._journal = JournalWriter(directory / f"{utc_stamp_name(stamp.utc)}{JOURNAL_SUFFIX}")
            self._journal.recording_started(str(path) if path else "", stamp)
        self._feedback.info(f"Gravando: {path.name if path else '(arquivo desconhecido)'}")
        log_event("gravacao_iniciada", path=str(path) if path else None, adotada=adopted)

    def _close_journal(self) -> None:
        if self._journal is not None:
            self._journal.close()
            self._journal = None

    def _end(self, stamp: Stamp) -> None:
        self._write("recording_stopped", lambda j: j.recording_stopped(stamp))
        self._close_journal()
        if self._construction_open:
            self._feedback.warn("construção ficou aberta: a ingestão fecha no fim da sessão, com aviso")
        self._feedback.info(f"Gravação encerrada: {self._count} marcador(es)")
        log_event("gravacao_encerrada", marcadores=self._count)
        self._recording, self._construction_open, self._paused = False, False, False
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
        in_journal = self._write("marker", lambda j: j.marker(kind, marker_id, stamp))
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
        if not in_journal:
            self._feedback.warn(f"{kind.value}: sem diário; só o marcador do OBS registrou o toque")
        elif not created:
            self._feedback.warn(f"{kind.value}: o OBS não criou o marcador no arquivo; o diário tem o toque")
        self._feedback.marked(kind, detail)
        log_event("marcador", kind=kind.value, marker_id=marker_id, no_arquivo=created)

    def close(self) -> None:
        """Encerra o gravador sem fechar a gravação: o OBS continua gravando e a retomada reabre o diário."""
        self._close_journal()


def _open_journal(directory: Path, current_file: Path | None) -> tuple[Path, bool] | None:
    """Diário de uma gravação em andamento (gravador reiniciado) e se ele a deixou pausada.

    É o último diário sem `recording_stopped` cujo arquivo atual é o que o OBS está gravando.
    """
    if current_file is None:
        return None
    for candidate in reversed(find_journals(directory)):
        events, _ = read_journal(candidate)
        files = [e.path for e in events if isinstance(e, RecordingStarted | FileChanged)]
        stopped = bool(events) and isinstance(events[-1], RecordingStopped)
        if files and not stopped and file_key(files[-1]) == file_key(str(current_file)):
            return candidate, _journal_paused(events)
    return None


def _journal_paused(events: list[JournalEvent]) -> bool:
    """O diário termina em pausa? (pausa ainda aberta: o último `paused` não teve `unpaused`)."""
    paused = False
    for event in events:
        if isinstance(event, RecordingStarted | Unpaused):
            paused = False
        elif isinstance(event, Paused):
            paused = True
    return paused
