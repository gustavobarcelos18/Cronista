"""Variantes de etapa (lacuna 3): duas execuções da mesma etapa coexistem sem se sobrescrever."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from cronista.config import Settings
from cronista.db.models import Artifact, Job, MediaFile
from cronista.db.session import make_engine, upgrade_db
from cronista.domain.models import StageResult
from cronista.pipeline import AlwaysFreeGate, StageContext, run_pipeline
from cronista.pipeline.stage import stage_key, stage_variant
from tests.test_pipeline import FakeStage, media  # noqa: F401  (fixture `media`)


class ModelStage:
    """Mesma etapa, modelo diferente: o que o benchmark de WER faz."""

    name = "transcribe"
    version = "1"
    uses_gpu = False

    def __init__(self, variant: str, calls: Counter[str], needs: tuple[str, ...] = ()) -> None:
        self.variant, self.needs, self._calls = variant, needs, calls

    def params(self, settings: Settings) -> dict[str, Any]:
        return {"model": self.variant}

    def run(self, ctx: StageContext) -> StageResult:
        self._calls[self.variant] += 1
        out = ctx.out_dir / "texto.txt"
        out.write_text(self.variant, encoding="utf-8")
        return StageResult(files=[str(out)], data={"model": self.variant})


def test_two_variants_coexist_and_are_cached_independently(
    db: Session,
    media: MediaFile,  # noqa: F811
    settings: Settings,
) -> None:
    calls: Counter[str] = Counter()
    stages = [ModelStage("turbo", calls), ModelStage("small", calls)]

    first = run_pipeline(db, media, stages, settings, AlwaysFreeGate())
    second = run_pipeline(db, media, stages, settings, AlwaysFreeGate())

    assert first.executed == ["transcribe:turbo", "transcribe:small"]
    assert second.cached == ["transcribe:turbo", "transcribe:small"] and not second.executed
    assert calls == Counter(turbo=1, small=1)
    assert first.results["transcribe:turbo"].data["model"] == "turbo"
    assert first.results["transcribe:small"].data["model"] == "small"
    artifacts = db.scalars(select(Artifact).where(Artifact.media_file_id == media.id)).all()
    assert sorted(a.variant for a in artifacts) == ["small", "turbo"]
    jobs = db.scalars(select(Job).where(Job.media_file_id == media.id)).all()
    assert sorted(j.variant for j in jobs) == ["small", "turbo"]
    assert len({Path(a.result_path).parent for a in artifacts}) == 2  # pastas distintas no cache


def test_downstream_stage_needs_a_variant_by_its_key(
    db: Session,
    media: MediaFile,  # noqa: F811
    settings: Settings,
) -> None:
    calls: Counter[str] = Counter()
    consumer = FakeStage("consumer", ("transcribe:turbo",), calls=calls)
    report = run_pipeline(db, media, [ModelStage("turbo", calls), consumer], settings, AlwaysFreeGate())
    assert report.executed == ["transcribe:turbo", "consumer"]

    # Acrescentar outra variante não invalida a primeira nem o consumidor dela.
    again = run_pipeline(
        db,
        media,
        [ModelStage("turbo", calls), consumer, ModelStage("small", calls)],
        settings,
        AlwaysFreeGate(),
    )
    assert again.cached == ["transcribe:turbo", "consumer"] and again.executed == ["transcribe:small"]


def test_variant_must_be_safe_for_a_folder_name() -> None:
    with pytest.raises(ValueError, match="variante inválida"):
        stage_variant(ModelStage("../fora", Counter()))
    assert stage_key(ModelStage("large-v3.int8", Counter())) == "transcribe:large-v3.int8"
    assert stage_key(FakeStage("a", calls=Counter())) == "a"


def test_old_stage_without_variant_keeps_working(
    db: Session,
    media: MediaFile,  # noqa: F811
    settings: Settings,
) -> None:
    calls: Counter[str] = Counter()
    run_pipeline(db, media, [FakeStage("a", calls=calls)], settings, AlwaysFreeGate())
    artifact = db.scalar(select(Artifact).where(Artifact.media_file_id == media.id))
    assert artifact is not None and artifact.variant == ""


def test_unique_constraint_is_per_variant(tmp_path: Path) -> None:
    engine = make_engine(tmp_path / "u.db")
    upgrade_db(engine)
    insert = text(
        "INSERT INTO artifact (media_file_id, stage, variant, cache_key, result_path, created_at) "
        "VALUES (1, 's', :v, 'k', 'r', '2026-01-01')"
    )
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO project (id, name, created_at) VALUES (1, 'p', '2026-01-01')"))
        conn.execute(
            text("INSERT INTO session (id, project_id, folder, created_at) VALUES (1, 1, 'x', '2026-01-01')")
        )
        conn.execute(
            text(
                "INSERT INTO media_file (id, session_id, path, ordinal, size_bytes) VALUES (1, 1, 'a', 0, 0)"
            )
        )
        for variant in ("", "turbo"):
            conn.execute(insert, {"v": variant})
    with pytest.raises(Exception, match="UNIQUE"), engine.begin() as conn:
        conn.execute(insert, {"v": "turbo"})
    engine.dispose()
