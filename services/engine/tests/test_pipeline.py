"""Orquestrador com etapas falsas: cache por hash, invalidação parcial, retomada, política de GPU."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.config import Settings
from cronista.db.models import Job, MediaFile, Project, RecordingSession
from cronista.domain.models import StageResult
from cronista.pipeline import AlwaysFreeGate, StageContext, StageFailedError, recover_orphans, run_pipeline


class FakeStage:
    uses_gpu = False

    def __init__(
        self,
        name: str,
        needs: tuple[str, ...] = (),
        *,
        version: str = "1",
        param: int = 0,
        calls: Counter[str],
        fail: bool = False,
        gpu: bool = False,
    ) -> None:
        self.name, self.needs, self.version = name, needs, version
        self._param, self._calls, self._fail = param, calls, fail
        self.uses_gpu = gpu

    def params(self, settings: Settings) -> dict[str, Any]:
        return {"p": self._param}

    def run(self, ctx: StageContext) -> StageResult:
        self._calls[self.name] += 1
        if self._fail:
            raise RuntimeError("queda simulada")
        out = ctx.out_dir / f"{self.name}.txt"
        out.write_text(self.name, encoding="utf-8")
        return StageResult(files=[str(out)])


@pytest.fixture
def media(db: Session, tmp_path: Path) -> MediaFile:
    video = tmp_path / "video.bin"
    video.write_bytes(b"conteudo" * 1000)
    project = Project(name="p")
    db.add(project)
    db.flush()
    session = RecordingSession(project_id=project.id, folder=str(tmp_path))
    db.add(session)
    db.flush()
    media = MediaFile(session_id=session.id, path=str(video))
    db.add(media)
    db.commit()
    return media


def chain(calls: Counter[str], **overrides: dict[str, Any]) -> list[FakeStage]:
    return [
        FakeStage("a", calls=calls, **overrides.get("a", {})),
        FakeStage("b", ("a",), calls=calls, **overrides.get("b", {})),
        FakeStage("c", ("b",), calls=calls, **overrides.get("c", {})),
    ]


def test_second_run_is_fully_cached(db: Session, media: MediaFile, settings: Settings) -> None:
    calls: Counter[str] = Counter()
    first = run_pipeline(db, media, chain(calls), settings, AlwaysFreeGate())
    second = run_pipeline(db, media, chain(calls), settings, AlwaysFreeGate())
    assert first.executed == ["a", "b", "c"]
    assert second.cached == ["a", "b", "c"] and second.executed == []
    assert calls == Counter(a=1, b=1, c=1)


def test_changing_a_parameter_invalidates_only_that_stage_and_the_next(
    db: Session, media: MediaFile, settings: Settings
) -> None:
    calls: Counter[str] = Counter()
    run_pipeline(db, media, chain(calls), settings, AlwaysFreeGate())
    report = run_pipeline(db, media, chain(calls, b={"param": 1}), settings, AlwaysFreeGate())
    assert report.cached == ["a"]
    assert report.executed == ["b", "c"]


def test_version_bump_invalidates_downstream(db: Session, media: MediaFile, settings: Settings) -> None:
    calls: Counter[str] = Counter()
    run_pipeline(db, media, chain(calls), settings, AlwaysFreeGate())
    report = run_pipeline(db, media, chain(calls, a={"version": "2"}), settings, AlwaysFreeGate())
    assert report.executed == ["a", "b", "c"]


def test_changed_media_invalidates_everything(db: Session, media: MediaFile, settings: Settings) -> None:
    calls: Counter[str] = Counter()
    run_pipeline(db, media, chain(calls), settings, AlwaysFreeGate())
    Path(media.path).write_bytes(b"outro conteudo" * 1000)
    report = run_pipeline(db, media, chain(calls), settings, AlwaysFreeGate())
    assert report.executed == ["a", "b", "c"]


def test_resume_after_failure_does_not_redo_finished_stages(
    db: Session, media: MediaFile, settings: Settings
) -> None:
    calls: Counter[str] = Counter()
    with pytest.raises(StageFailedError):
        run_pipeline(db, media, chain(calls, c={"fail": True}), settings, AlwaysFreeGate())
    job = db.scalar(select(Job).where(Job.stage == "c"))
    assert job is not None and job.status == "failed" and "queda simulada" in (job.error or "")

    report = run_pipeline(db, media, chain(calls), settings, AlwaysFreeGate())
    assert report.cached == ["a", "b"] and report.executed == ["c"]
    assert calls == Counter(a=1, b=1, c=2)


def test_orphan_running_jobs_return_to_pending_and_rerun(
    db: Session, media: MediaFile, settings: Settings
) -> None:
    calls: Counter[str] = Counter()
    run_pipeline(db, media, chain(calls), settings, AlwaysFreeGate())
    # Simula um processo morto no meio da etapa c: job `running` e saída apagada.
    job = db.scalar(select(Job).where(Job.stage == "c"))
    assert job is not None
    job.status = "running"
    db.commit()
    for f in settings.cache_dir.rglob("c.txt"):
        f.unlink()

    assert recover_orphans(db) == 1
    db.refresh(job)
    assert job.status == "pending"
    report = run_pipeline(db, media, chain(calls), settings, AlwaysFreeGate())
    assert report.cached == ["a", "b"] and report.executed == ["c"]
    db.refresh(job)
    assert job.status == "done"


def test_gpu_stage_waits_until_gate_is_free(db: Session, media: MediaFile, settings: Settings) -> None:
    class Busy:
        def __init__(self) -> None:
            self.checks = 0

        def is_free(self) -> bool:
            self.checks += 1
            return self.checks > 3

    gate = Busy()
    sleeps: list[float] = []
    calls: Counter[str] = Counter()
    stages = [FakeStage("g", calls=calls, gpu=True)]
    run_pipeline(db, media, stages, settings, gate, sleep=sleeps.append)
    assert len(sleeps) == 3 and calls["g"] == 1


def test_cpu_stage_also_waits_for_the_gate(db: Session, media: MediaFile, settings: Settings) -> None:
    """CLAUDE.md: todo processamento pausa com o OBS gravando ou jogo em tela cheia, não só o de GPU."""

    class Busy:
        def __init__(self) -> None:
            self.checks = 0

        def is_free(self) -> bool:
            self.checks += 1
            return self.checks > 2

    gate, sleeps = Busy(), []  # type: ignore[var-annotated]
    calls: Counter[str] = Counter()
    run_pipeline(db, media, [FakeStage("x", calls=calls)], settings, gate, sleep=sleeps.append)
    assert len(sleeps) == 2 and calls["x"] == 1


def test_cached_stage_does_not_consult_the_gate(db: Session, media: MediaFile, settings: Settings) -> None:
    calls: Counter[str] = Counter()
    run_pipeline(db, media, [FakeStage("x", calls=calls)], settings, AlwaysFreeGate())

    class Exploding:
        def is_free(self) -> bool:
            raise AssertionError("etapa em cache não roda, logo não espera o gate")

    report = run_pipeline(db, media, [FakeStage("x", calls=calls)], settings, Exploding())
    assert report.cached == ["x"] and calls["x"] == 1


def test_on_result_runs_per_stage_even_if_a_later_stage_fails(
    db: Session, media: MediaFile, settings: Settings
) -> None:
    calls: Counter[str] = Counter()
    stages = [FakeStage("a", calls=calls), FakeStage("b", ("a",), calls=calls, fail=True)]
    seen: list[str] = []
    with pytest.raises(StageFailedError):
        run_pipeline(
            db,
            media,
            stages,
            settings,
            AlwaysFreeGate(),
            on_result=lambda stage, _result: seen.append(stage.name),
        )
    assert seen == ["a"]  # o resultado da etapa pronta chegou a quem grava, mesmo com a seguinte falhando


def test_result_persistence_failure_marks_the_job_failed(
    db: Session, media: MediaFile, settings: Settings
) -> None:
    class Unserializable(FakeStage):
        def run(self, ctx: StageContext) -> StageResult:
            result = super().run(ctx)
            result.files = [object()]  # type: ignore[list-item]  # o dump do resultado vai falhar
            return result

    calls: Counter[str] = Counter()
    with pytest.raises(StageFailedError):
        run_pipeline(db, media, [Unserializable("a", calls=calls)], settings, AlwaysFreeGate())
    job = db.scalars(select(Job)).one()
    assert job.status == "failed" and job.error


def test_fingerprint_covers_the_tail_of_small_files(tmp_path: Path) -> None:
    from cronista.pipeline.cache import fingerprint_file

    path = tmp_path / "f.bin"
    path.write_bytes(b"a" * (1_500_000))
    before = fingerprint_file(path)
    path.write_bytes(b"a" * 1_499_999 + b"b")
    assert fingerprint_file(path) != before
