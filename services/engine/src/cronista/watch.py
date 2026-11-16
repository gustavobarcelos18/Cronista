"""Serviço do engine: observa a pasta de gravação e ingere cada gravação quando ela termina (decisão D1).

Uma gravação = um diário `.markers.jsonl` (escrito pelo gravador de marcadores). A sessão no banco tem o
diário como origem, então várias gravações na mesma pasta do OBS viram sessões separadas.

Disparo: o diário termina em `recording_stopped` **e** os arquivos pararam de crescer há `settle_seconds`
(o OBS ainda finaliza o Hybrid MP4 depois do evento). Gravação que o OBS não fechou (queda, PC desligado)
fica com o diário aberto: depois de `abandoned_after_hours` sem o arquivo crescer, é tratada como interrompida
e entra no mesmo caminho (o remux da ingestão cobre o arquivo cortado).

Sem biblioteca de observação de arquivos: consulta a pasta a cada poucos segundos, o que funciona igual em
disco local, externo e de rede, e não perde evento se o serviço estava fechado.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.config import Settings
from cronista.db.models import Artifact, RecordingSession
from cronista.domain.journal import FileChanged, JournalEvent, RecordingStarted, RecordingStopped
from cronista.ingest.journal import find_journals, read_journal
from cronista.ingest.service import ingest_files
from cronista.logging_setup import log_event
from cronista.pipeline import GpuGate
from cronista.recorder.files import SLACK

AFTER_STOP_SLACK_S = 60.0


@dataclass
class Recording:
    """O que o diário diz sobre uma gravação."""

    journal: Path
    ended: bool
    started: datetime | None
    last_event: datetime
    paths: list[str]  # na ordem; "" = arquivo que o gravador não achou (sempre o primeiro)


@dataclass
class Processed:
    journal: Path
    session_id: int | None = None
    files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    abandoned: bool = False


def inspect_journal(journal: Path) -> Recording | None:
    events, _ = read_journal(journal)
    paths = [e.path for e in events if isinstance(e, RecordingStarted | FileChanged)]
    if not events or not paths:
        return None
    started = next((e.utc for e in events if isinstance(e, RecordingStarted)), None)
    return Recording(journal, _ended(events), started, events[-1].utc, paths)


def _ended(events: list[JournalEvent]) -> bool:
    return isinstance(events[-1], RecordingStopped)


def _name(raw: str) -> str:
    return Path(raw.replace("\\", "/")).name


def resolve_files(rec: Recording, directory: Path, settings: Settings) -> tuple[list[Path], list[str]]:
    """Arquivos de vídeo da gravação. O caminho do diário vale; se o disco mudou, vale o nome na pasta."""
    files: list[Path] = []
    warnings: list[str] = []
    for raw in (p for p in rec.paths if p):
        candidate = Path(raw)
        if not candidate.is_file():
            candidate = directory / _name(raw)
        if candidate.is_file():
            if candidate not in files:
                files.append(candidate)
        else:
            warnings.append(f"arquivo {_name(raw)} do diário não existe mais")

    if (
        "" in rec.paths
    ):  # o gravador não achou o primeiro arquivo: o mais antigo, entre os que cabem na gravação
        floor = (rec.started.timestamp() - SLACK.total_seconds()) if rec.started else 0.0
        ceiling = rec.last_event.timestamp() + AFTER_STOP_SLACK_S
        exts = {e.lower() for e in settings.video_extensions}
        pool = sorted(
            (
                p
                for p in directory.iterdir()
                if p.is_file()
                and p.suffix.lower() in exts
                and p not in files
                and floor <= p.stat().st_mtime <= ceiling
            ),
            key=lambda p: p.stat().st_mtime,
        )
        if pool:
            files.insert(0, pool[0])
            warnings.append(f"arquivo inicial deduzido pela data: {pool[0].name}")
        else:
            warnings.append("o diário não sabe o arquivo inicial e nenhum vídeo da pasta combina")
    return files, warnings


def is_complete(db: Session, session: RecordingSession) -> bool:
    """Sessão inteira ingerida: tem arquivos e todos chegaram à última etapa (`audio`)."""
    if not session.media_files:
        return False
    return all(
        db.scalar(select(Artifact.id).where(Artifact.media_file_id == m.id, Artifact.stage == "audio"))
        is not None
        for m in session.media_files
    )


def scan_once(
    db: Session,
    settings: Settings,
    gate: GpuGate,
    watch_dir: Path,
    project: str = "default",
    *,
    now: Callable[[], float] = time.time,
    failed: dict[Path, float] | None = None,
) -> list[Processed]:
    """Uma varredura: ingere as gravações prontas que ainda não foram ingeridas (ou ficaram incompletas).

    `failed` guarda, por diário, a data de modificação em que a ingestão falhou: só tenta de novo se o diário
    mudar (ou o serviço reiniciar), para uma falha não virar um laço quente.
    """
    failed = failed if failed is not None else {}
    done: list[Processed] = []
    for journal in find_journals(watch_dir):
        origin = str(journal.resolve())
        session = db.scalar(select(RecordingSession).where(RecordingSession.folder == origin))
        if session is not None and is_complete(db, session):
            continue
        mtime = journal.stat().st_mtime
        if failed.get(journal) == mtime:
            continue
        rec = inspect_journal(journal)
        if rec is None:
            continue
        files, warnings = resolve_files(rec, watch_dir, settings)

        newest = max([mtime, *(f.stat().st_mtime for f in files)])
        idle = now() - newest
        abandoned = not rec.ended
        wait = settings.abandoned_after_hours * 3600 if abandoned else settings.settle_seconds
        if idle < wait:
            continue

        result = Processed(journal, files=files, warnings=warnings, abandoned=abandoned)
        if abandoned:
            result.warnings.append(
                "gravação sem recording_stopped (OBS fechou ou o PC caiu): tratada como interrompida"
            )
        if not files:
            result.error = "nenhum arquivo de vídeo encontrado para esta gravação"
        else:
            log_event("ingestao_automatica", journal=journal.name, files=[f.name for f in files])
            try:
                report = ingest_files(db, origin, files, settings, gate, project)
            except Exception as exc:
                result.error = str(exc)
            else:
                result.session_id = report.session_id
                result.warnings += report.markers.warnings
                if not report.ok:
                    result.error = "; ".join(f"{Path(p).name}: {e}" for p, e in report.failures.items())
        if result.error:
            failed[journal] = mtime
        done.append(result)
    return done


def serve(
    db: Session,
    settings: Settings,
    gate: GpuGate,
    watch_dir: Path,
    project: str,
    report: Callable[[Processed], None],
    *,
    max_scans: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
) -> None:
    """Laço do serviço (Ctrl+C sai). `max_scans` existe para `--once` e para os testes."""
    failed: dict[Path, float] = {}
    scans = 0
    while max_scans is None or scans < max_scans:
        for item in scan_once(db, settings, gate, watch_dir, project, now=now, failed=failed):
            report(item)
        scans += 1
        if max_scans is None or scans < max_scans:
            sleep(settings.watch_poll_seconds)
