"""Leitura e escrita do diário `.markers.jsonl` (o formato está em `domain.journal`)."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Stamp:
    """Instante de um evento (relógio monotônico + UTC), capturado quando ele acontece.

    O gravador tira o carimbo no momento do toque e só depois escreve a linha, que pode esperar a
    resolução do arquivo; sem isso o tempo do marcador sairia atrasado.
    """

    mono_s: float
    utc: datetime


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

    def now(self) -> Stamp:
        return Stamp(self._mono(), self._utc())

    def _write(self, event: JournalEvent) -> None:
        self._handle.write(event.model_dump_json().encode("utf-8") + b"\n")
        self._sync()

    def recording_started(self, path: str, at: Stamp | None = None) -> None:
        s = at or self.now()
        self._write(RecordingStarted(mono_s=s.mono_s, utc=s.utc, path=path))

    def paused(self, at: Stamp | None = None) -> None:
        s = at or self.now()
        self._write(Paused(mono_s=s.mono_s, utc=s.utc))

    def unpaused(self, at: Stamp | None = None) -> None:
        s = at or self.now()
        self._write(Unpaused(mono_s=s.mono_s, utc=s.utc))

    def file_changed(self, path: str, at: Stamp | None = None) -> None:
        s = at or self.now()
        self._write(FileChanged(mono_s=s.mono_s, utc=s.utc, path=path))

    def recording_stopped(self, at: Stamp | None = None) -> None:
        s = at or self.now()
        self._write(RecordingStopped(mono_s=s.mono_s, utc=s.utc))

    def marker(self, kind: MarkerKind, marker_id: str, at: Stamp | None = None) -> None:
        s = at or self.now()
        self._write(MarkerPressed(mono_s=s.mono_s, utc=s.utc, kind=kind, marker_id=marker_id))

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
