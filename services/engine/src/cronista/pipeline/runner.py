"""Execução das etapas de um arquivo: cache, jobs persistidos, retomada e política de GPU."""

from __future__ import annotations

import logging
import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from cronista.config import Settings
from cronista.db.models import Artifact, Job, MediaFile
from cronista.domain.models import StageResult
from cronista.logging_setup import log_event
from cronista.pipeline.cache import compute_key, fingerprint_file
from cronista.pipeline.gpu import GpuGate, wait_until_free
from cronista.pipeline.stage import Stage, StageContext, stage_key, stage_variant

RESULT_FILE = "result.json"


class StageFailedError(Exception):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"etapa '{stage}' falhou: {message}")
        self.stage = stage


@dataclass
class PipelineReport:
    executed: list[str] = field(default_factory=list)
    cached: list[str] = field(default_factory=list)
    results: dict[str, StageResult] = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(UTC)


def recover_orphans(db: Session) -> int:
    """Jobs que ficaram `running` (processo morto) voltam para `pending`."""
    result = db.execute(update(Job).where(Job.status == "running").values(status="pending"))
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


def _load_cached(artifact: Artifact | None, key: str) -> StageResult | None:
    if artifact is None or artifact.cache_key != key:
        return None
    path = Path(artifact.result_path)
    if not path.is_file():
        return None
    result = StageResult.model_validate_json(path.read_text(encoding="utf-8"))
    if any(not Path(f).exists() for f in result.files):
        return None
    return result


def run_pipeline(
    db: Session,
    media: MediaFile,
    stages: Sequence[Stage],
    settings: Settings,
    gate: GpuGate,
    sleep: Callable[[float], None] = time.sleep,
    on_result: Callable[[Stage, StageResult], None] | None = None,
) -> PipelineReport:
    """Roda as etapas na ordem dada (já topológica). Etapa com cache válido é pulada.

    `on_result` é chamado assim que cada etapa termina (executada ou em cache), para quem precisa gravar o
    resultado sem esperar as etapas seguintes (uma falha tardia não pode perder o que já está pronto).
    """
    report = PipelineReport()
    keys: dict[str, str] = {}
    media_path = Path(media.path)
    root_fp = fingerprint_file(media_path)

    for stage in stages:
        name, variant = stage_key(stage), stage_variant(stage)
        key = compute_key(
            name, stage.version, stage.params(settings), root_fp, [keys[n] for n in stage.needs]
        )
        keys[name] = key

        artifact = db.scalar(
            select(Artifact).where(
                Artifact.media_file_id == media.id, Artifact.stage == stage.name, Artifact.variant == variant
            )
        )
        cached = _load_cached(artifact, key)
        if cached is not None:
            report.results[name] = cached
            report.cached.append(name)
            if on_result is not None:
                on_result(stage, cached)
            log_event("etapa_em_cache", media_file_id=media.id, stage=name, cache_key=key[:12])
            continue

        job = db.scalar(
            select(Job).where(Job.media_file_id == media.id, Job.stage == stage.name, Job.variant == variant)
        )
        if job is None:
            job = Job(media_file_id=media.id, stage=stage.name, variant=variant, attempts=0)
            db.add(job)
        job.status, job.cache_key, job.error = "running", key, None
        job.attempts += 1
        job.started_at, job.finished_at = _now(), None
        db.commit()

        def wait_for_gpu(working: bool = True, stage_name: str = name) -> None:
            wait_until_free(
                gate,
                settings.gpu_poll_seconds,
                sleep,
                working=working,
                media_file_id=media.id,
                stage=stage_name,
            )

        wait_for_gpu(working=False)  # todo processamento pausa com o OBS gravando ou jogo em tela cheia

        out_dir = settings.cache_dir / str(media.id) / stage.name
        if variant:
            out_dir = out_dir / variant
        out_dir = out_dir / key[:12]
        if out_dir.exists():
            shutil.rmtree(out_dir)  # sobra de uma execução interrompida
        out_dir.mkdir(parents=True)

        ctx = StageContext(
            media_path=media_path,
            out_dir=out_dir,
            settings=settings,
            inputs={n: report.results[n] for n in stage.needs},
            wait_for_gpu=wait_for_gpu,
        )
        log_event("etapa_iniciada", media_file_id=media.id, stage=name, job_id=job.id)
        try:
            result = stage.run(ctx)
            result_path = out_dir / RESULT_FILE
            result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
            if artifact is None:
                artifact = Artifact(
                    media_file_id=media.id, stage=stage.name, variant=variant, cache_key=key, result_path=""
                )
                db.add(artifact)
            else:  # troca de versão do cache: apaga a saída antiga
                old_dir = Path(artifact.result_path).parent
                if old_dir.exists() and old_dir != out_dir:
                    shutil.rmtree(old_dir, ignore_errors=True)
            artifact.cache_key, artifact.result_path, artifact.created_at = key, str(result_path), _now()
            job.status, job.finished_at = "done", _now()
            db.commit()
        except Exception as exc:  # inclui a gravação do resultado: o job nunca fica `running` para sempre
            db.rollback()
            job.status, job.error, job.finished_at = "failed", str(exc), _now()
            db.commit()
            log_event("etapa_falhou", level=logging.ERROR, media_file_id=media.id, stage=name, error=str(exc))
            raise StageFailedError(name, str(exc)) from exc

        report.results[name] = result
        report.executed.append(name)
        if on_result is not None:
            on_result(stage, result)
        log_event("etapa_concluida", media_file_id=media.id, stage=name, warnings=result.warnings)

    return report
