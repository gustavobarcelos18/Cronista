"""Descobre qual arquivo o OBS está gravando.

O obs-websocket não informa o caminho ao iniciar a gravação (`outputPath` só vem ao parar, e
`newOutputPath` só nas divisões). Como o gravador roda no mesmo PC do OBS, procuramos o arquivo de vídeo
mais novo na pasta de gravação (`GetRecordDirectory`). ⚠️ Validar com o OBS real na 1C.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Collection
from datetime import UTC, datetime, timedelta
from pathlib import Path

SLACK = timedelta(seconds=3)


def newest_video(directory: Path, extensions: Collection[str], since: datetime) -> Path | None:
    """Arquivo de vídeo modificado depois de `since` (menos uma folga), o mais novo; None se não houver."""
    floor = (since - SLACK).timestamp()
    exts = {e.lower() for e in extensions}
    best: tuple[float, Path] | None = None
    if not directory.is_dir():
        return None
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.lower() not in exts:
            continue
        mtime = path.stat().st_mtime
        if mtime >= floor and (best is None or mtime > best[0]):
            best = (mtime, path)
    return best[1] if best else None


async def find_recording_file(
    directory: Path,
    extensions: Collection[str],
    since: datetime,
    *,
    timeout_s: float = 3.0,
    poll_s: float = 0.25,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Path | None:
    """Espera o arquivo aparecer (o OBS cria ao iniciar, mas pode levar alguns décimos de segundo)."""
    waited = 0.0
    while True:
        found = newest_video(directory, extensions, since)
        if found is not None or waited >= timeout_s:
            return found
        await sleep(poll_s)
        waited += poll_s


def utc_stamp_name(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("gravacao-%Y%m%d-%H%M%S")
