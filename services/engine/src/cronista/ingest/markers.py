"""Ingestão de marcadores de uma sessão: diário + marcadores do arquivo → tabela `marker`.

Passo idempotente da sessão (não é uma etapa com cache por arquivo): o diário pertence à sessão e pode
crescer entre uma ingestão e outra, e ler capítulos é barato. Cada execução refaz as linhas da sessão.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from cronista.config import Settings
from cronista.db.models import Marker, MediaFile, RecordingSession
from cronista.domain.models import MarkerKind
from cronista.domain.timeline import (
    JournalMarker,
    MarkerSource,
    ResolvedMarker,
    file_key,
    reconcile_file,
    reconstruct_media_times,
)
from cronista.ingest.ffmpeg import probe_chapters
from cronista.ingest.journal import find_journals, read_journal

IMPLICIT_DAY_ID = "dia-implicito"


@dataclass(frozen=True)
class IngestedFile:
    """Arquivo da sessão já normalizado: `media` é o original; `ready` é o que o ffprobe deve ler."""

    media: MediaFile
    ready: Path
    duration_s: float | None


@dataclass
class MarkerReport:
    count: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Row:
    ordinal: int
    media_file_id: int
    marker: ResolvedMarker
    phase: str | None = None


def ingest_markers(
    db: Session, session: RecordingSession, files: Sequence[IngestedFile], settings: Settings
) -> MarkerReport:
    report = MarkerReport()
    if not files:
        return report

    journal_markers: list[JournalMarker] = []
    for journal_path in find_journals(Path(session.folder)):
        events, warnings = read_journal(journal_path)
        report.warnings += warnings
        rebuilt = reconstruct_media_times(events)
        journal_markers += rebuilt.markers
        report.warnings += [f"{journal_path.name}: {w}" for w in rebuilt.warnings]

    known = {file_key(f.media.path) for f in files}
    for marker in journal_markers:
        if file_key(marker.file_name) not in known:
            report.warnings.append(
                f"marcador {marker.kind.value}|{marker.marker_id} aponta para {marker.file_name!r}, "
                "que não está nesta sessão: ignorado"
            )

    rows: list[_Row] = []
    for file in sorted(files, key=lambda f: f.media.ordinal):
        name = Path(file.media.path).name
        mine = [m for m in journal_markers if file_key(m.file_name) == file_key(name)]
        for resolved in reconcile_file(name, mine, probe_chapters(settings, file.ready)):
            rows.append(_Row(file.media.ordinal, file.media.id, resolved))
            if resolved.warning:
                report.warnings.append(f"{name} @ {resolved.media_time_s:.1f}s: {resolved.warning}")

    _pair_constructions(rows, files, report)
    _add_implicit_day(db, session, rows, files, report)

    db.execute(delete(Marker).where(Marker.session_id == session.id))
    for row in sorted(rows, key=lambda r: (r.ordinal, r.marker.media_time_s)):
        m = row.marker
        db.add(
            Marker(
                session_id=session.id,
                media_file_id=row.media_file_id,
                marker_id=m.marker_id,
                kind=m.kind.value,
                media_time_s=m.media_time_s,
                source=m.source.value,
                phase=row.phase,
                warning=m.warning,
            )
        )
    db.commit()
    report.count = len(rows)
    return report


def _pair_constructions(rows: list[_Row], files: Sequence[IngestedFile], report: MarkerReport) -> None:
    """`Construção ▶/■` é uma tecla só que alterna: ímpares abrem, pares fecham. Aberta no fim, fecha."""
    ordered = sorted(
        (r for r in rows if r.marker.kind is MarkerKind.CONSTRUCAO),
        key=lambda r: (r.ordinal, r.marker.media_time_s),
    )
    for index, row in enumerate(ordered):
        row.phase = "start" if index % 2 == 0 else "end"
    if ordered and ordered[-1].phase == "start":
        opened = ordered[-1]
        last = max(files, key=lambda f: f.media.ordinal)
        floor = opened.marker.media_time_s if opened.ordinal == last.media.ordinal else 0.0
        end_time = max(last.duration_s or 0.0, floor)
        warning = "construção aberta no fim da sessão: fechada automaticamente"
        report.warnings.append(f"{opened.marker.marker_id}: {warning}")
        rows.append(
            _Row(
                last.media.ordinal,
                last.media.id,
                ResolvedMarker(
                    f"{opened.marker.marker_id}-fim",
                    MarkerKind.CONSTRUCAO,
                    Path(last.media.path).name,
                    end_time,
                    MarkerSource.SYNTHETIC,
                    warning,
                ),
                phase="end",
            )
        )


def _add_implicit_day(
    db: Session,
    session: RecordingSession,
    rows: list[_Row],
    files: Sequence[IngestedFile],
    report: MarkerReport,
) -> None:
    """Primeira sessão do projeto sem `Novo dia`: abre um dia implícito no início, sem número.

    Uma sessão sem `Novo dia` que vem depois de outra continua o dia anterior (nada a fazer).
    """
    if any(r.marker.kind is MarkerKind.NOVO_DIA for r in rows):
        return
    earlier_days = db.scalar(
        select(func.count())
        .select_from(Marker)
        .join(RecordingSession, Marker.session_id == RecordingSession.id)
        .where(
            RecordingSession.project_id == session.project_id,
            RecordingSession.id < session.id,
            Marker.kind == MarkerKind.NOVO_DIA.value,
        )
    )
    if earlier_days:
        return
    first = min(files, key=lambda f: f.media.ordinal)
    warning = "nenhum 'Novo dia' no início do projeto: dia implícito aberto no começo da sessão"
    report.warnings.append(warning)
    rows.append(
        _Row(
            first.media.ordinal,
            first.media.id,
            ResolvedMarker(
                IMPLICIT_DAY_ID,
                MarkerKind.NOVO_DIA,
                Path(first.media.path).name,
                0.0,
                MarkerSource.SYNTHETIC,
                warning,
            ),
        )
    )
