"""Leitura e escrita do diário `.markers.jsonl` (o formato está em `domain.journal`)."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import IO, Self

from pydantic import ValidationError

from cronista.domain.journal import (
    FileChanged,
    JournalEvent,
    MarkerPressed,
    Paused,
    RecordingStarted,
    RecordingStopped,
    Unpaused,
    journal_event_adapter,
)
from cronista.domain.models import MarkerKind

JOURNAL_SUFFIX = ".markers.jsonl"


def find_journals(folder: Path) -> list[Path]:
    return sorted(folder.glob(f"*{JOURNAL_SUFFIX}"))


def read_journal(path: Path) -> tuple[list[JournalEvent], list[str]]:
    """Lê o diário. Linha inválida (corte por queda) é pulada e vira aviso; nunca derruba a leitura."""
    events: list[JournalEvent] = []
    warnings: list[str] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                events.append(journal_event_adapter.validate_json(line))
            except ValidationError:
                warnings.append(f"{path.name}:{number}: linha inválida do diário ignorada")
    return events, warnings


class JournalWriter:
    """Escreve eventos com `flush` + `fsync` a cada linha: um toque confirmado sobrevive a uma queda.

    Ao reabrir um diário cuja última linha ficou cortada (sem `\\n`), começa por uma quebra de linha, para o
    próximo evento não ser colado no resto da linha quebrada.
    """

    def __init__(
        self,
        path: Path,
        mono: Callable[[], float] = time.monotonic,
        utc: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        needs_break = path.exists() and path.stat().st_size > 0 and not _ends_with_newline(path)
        self._handle: IO[bytes] = path.open("ab")
        self._mono, self._utc = mono, utc
        if needs_break:
            self._handle.write(b"\n")
            self._sync()

    def _sync(self) -> None:
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def _write(self, event: JournalEvent) -> None:
        self._handle.write(event.model_dump_json().encode("utf-8") + b"\n")
        self._sync()

    def recording_started(self, path: str) -> None:
        self._write(RecordingStarted(mono_s=self._mono(), utc=self._utc(), path=path))

    def paused(self) -> None:
        self._write(Paused(mono_s=self._mono(), utc=self._utc()))

    def unpaused(self) -> None:
        self._write(Unpaused(mono_s=self._mono(), utc=self._utc()))

    def file_changed(self, path: str) -> None:
        self._write(FileChanged(mono_s=self._mono(), utc=self._utc(), path=path))

    def recording_stopped(self) -> None:
        self._write(RecordingStopped(mono_s=self._mono(), utc=self._utc()))

    def marker(self, kind: MarkerKind, marker_id: str) -> None:
        self._write(MarkerPressed(mono_s=self._mono(), utc=self._utc(), kind=kind, marker_id=marker_id))

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def _ends_with_newline(path: Path) -> bool:
    with path.open("rb") as handle:
        handle.seek(-1, os.SEEK_END)
        return handle.read(1) == b"\n"
