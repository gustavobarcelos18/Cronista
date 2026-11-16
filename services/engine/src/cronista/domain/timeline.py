"""Tempo de mídia dos marcadores: reconstrução a partir do diário e reconciliação com o arquivo.

Regras da seção 4 do plano mestre:
- o tempo de mídia é `toque - início do arquivo - pausas acumuladas`, dentro do arquivo vigente;
- bate com o marcador do arquivo (≈ 1 s) → usa o do arquivo; só existe o diário → usa o reconstruído;
  diverge → usa o do arquivo e avisa; só existe no arquivo → `Momento` com aviso;
  toque fora de gravação → ignorado, com aviso.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from cronista.domain.journal import (
    FileChanged,
    JournalEvent,
    MarkerPressed,
    Paused,
    RecordingStarted,
    RecordingStopped,
    Unpaused,
    parse_chapter_title,
)
from cronista.domain.models import MarkerKind

TOLERANCE_S = 1.0


class MarkerSource(StrEnum):
    FILE = "file"  # tempo lido do marcador do OBS dentro do arquivo
    JOURNAL = "journal"  # tempo reconstruído a partir do diário
    SYNTHETIC = "synthetic"  # criado pelo sistema (fim de construção em aberto, dia implícito)


@dataclass(frozen=True)
class JournalMarker:
    """Toque do diário já convertido para o tempo de mídia do arquivo vigente."""

    marker_id: str
    kind: MarkerKind
    file_name: str
    media_time_s: float


@dataclass(frozen=True)
class FileChapter:
    """Marcador (capítulo) lido de dentro do arquivo, com o nome que o OBS gravou."""

    title: str
    media_time_s: float


@dataclass(frozen=True)
class ResolvedMarker:
    marker_id: str
    kind: MarkerKind
    file_name: str
    media_time_s: float
    source: MarkerSource
    warning: str | None = None


@dataclass
class Reconstruction:
    markers: list[JournalMarker] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def file_key(path: str) -> str:
    """Chave de comparação de arquivos: só o nome (o diário guarda o caminho do ponto de vista do OBS)."""
    return path.replace("\\", "/").rsplit("/", 1)[-1].lower()


def reconstruct_media_times(events: Sequence[JournalEvent]) -> Reconstruction:
    """Percorre o diário em ordem e converte cada `marker` em tempo de mídia dentro do arquivo vigente."""
    out = Reconstruction()
    recording = False
    current_file = ""
    file_start = 0.0
    paused_total = 0.0
    paused_since: float | None = None

    for event in events:
        match event:
            case RecordingStarted():
                recording, current_file = True, event.path
                file_start, paused_total, paused_since = event.mono_s, 0.0, None
            case Paused():
                if recording and paused_since is None:
                    paused_since = event.mono_s
            case Unpaused():
                if paused_since is not None:
                    paused_total += event.mono_s - paused_since
                    paused_since = None
            case FileChanged():
                if not recording:  # divisão sem `recording_started` (diário cortado no início)
                    recording = True
                    out.warnings.append(
                        f"file_changed sem recording_started; assumindo gravação em {event.path}"
                    )
                current_file = event.path
                file_start, paused_total = event.mono_s, 0.0
                if paused_since is not None:  # a pausa continua valendo no arquivo novo
                    paused_since = event.mono_s
            case RecordingStopped():
                recording, paused_since = False, None
            case MarkerPressed():
                if not recording:
                    out.warnings.append(
                        f"marcador {event.kind.value}|{event.marker_id} fora de gravação: ignorado"
                    )
                    continue
                elapsed = event.mono_s - file_start - paused_total
                if paused_since is not None:
                    elapsed -= event.mono_s - paused_since
                    out.warnings.append(
                        f"marcador {event.kind.value}|{event.marker_id} durante pausa: "
                        "colocado no ponto onde a gravação parou"
                    )
                out.markers.append(
                    JournalMarker(event.marker_id, event.kind, current_file, max(elapsed, 0.0))
                )
    return out


def reconcile_file(
    file_name: str,
    journal: Sequence[JournalMarker],
    chapters: Sequence[FileChapter],
    tolerance_s: float = TOLERANCE_S,
) -> list[ResolvedMarker]:
    """Reconcilia, para um arquivo, os toques do diário com os marcadores gravados dentro dele (pelo `id`)."""
    resolved: list[ResolvedMarker] = []
    by_id: dict[str, tuple[MarkerKind, FileChapter]] = {}
    orphans: list[tuple[int, FileChapter]] = []
    for index, chapter in enumerate(chapters):
        parsed = parse_chapter_title(chapter.title)
        if parsed is None:
            orphans.append((index, chapter))
        else:
            by_id[parsed[1]] = (parsed[0], chapter)

    seen: set[str] = set()
    for marker in journal:
        seen.add(marker.marker_id)
        match = by_id.get(marker.marker_id)
        if match is None:  # só o diário
            resolved.append(
                ResolvedMarker(
                    marker.marker_id, marker.kind, file_name, marker.media_time_s, MarkerSource.JOURNAL
                )
            )
            continue
        chapter_time = match[1].media_time_s
        delta = abs(chapter_time - marker.media_time_s)
        warning = None
        if delta > tolerance_s:
            warning = (
                f"diário e arquivo divergem em {delta:.1f}s "
                f"(diário {marker.media_time_s:.1f}s, arquivo {chapter_time:.1f}s); usei o arquivo"
            )
        resolved.append(
            ResolvedMarker(marker.marker_id, marker.kind, file_name, chapter_time, MarkerSource.FILE, warning)
        )

    for marker_id, (_, chapter) in by_id.items():  # só no arquivo
        if marker_id not in seen:
            resolved.append(_file_only(file_name, marker_id, chapter))
    for index, chapter in orphans:  # capítulo sem o nome `tipo|id` (ex.: hotkey nativa do OBS)
        resolved.append(_file_only(file_name, f"arquivo-{index}", chapter))

    resolved.sort(key=lambda m: m.media_time_s)
    return resolved


def _file_only(file_name: str, marker_id: str, chapter: FileChapter) -> ResolvedMarker:
    return ResolvedMarker(
        marker_id,
        MarkerKind.MOMENTO,
        file_name,
        chapter.media_time_s,
        MarkerSource.FILE,
        f"marcador só no arquivo ({chapter.title!r}): tratado como Momento",
    )
