"""Regressões da auditoria 10A (bloco A): cada teste falhava antes da correção."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.orm import Session

from cronista import watch
from cronista.audio.ports import AudioModels
from cronista.audio.stages import analysis_stages
from cronista.config import Settings
from cronista.ingest import service
from cronista.ingest.markers import MarkerReport
from cronista.pipeline import AlwaysFreeGate, StageFailedError
from cronista.watch import Recording
from tests.fakes_audio import FakeClassifier


def test_scream_detector_is_off_by_default_and_opt_in() -> None:
    models = AudioModels(classifier=FakeClassifier())

    def variants(stages: list) -> list[str]:  # type: ignore[type-arg]
        return [getattr(s, "variant", "") for s in stages]

    assert not any("grito" in v for v in variants(analysis_stages(models)))
    assert any("grito" in v for v in variants(analysis_stages(models, scream_enabled=True)))
    assert not Settings(env="t", data_dir=Path("x")).scream_enabled


def test_scream_stage_is_cpu_only_and_model_stages_keep_gpu() -> None:
    stages = analysis_stages(AudioModels(classifier=FakeClassifier()), scream_enabled=True)
    by_variant = {cast(Any, s).variant: s.uses_gpu for s in stages if s.name == "sound_events"}
    assert [v for v, gpu in by_variant.items() if not gpu and "grito" in v]
    assert any(gpu for gpu in by_variant.values())


def test_same_file_with_different_spelling_resolves_to_one_path(tmp_path: Path, settings: Settings) -> None:
    folder = tmp_path / "obs"
    folder.mkdir()
    video = folder / "a.mp4"
    video.write_bytes(b"x")
    roundabout = str(folder / ".." / "obs" / "a.mp4")
    rec = Recording(tmp_path / "j.jsonl", True, None, datetime.now(), [roundabout, str(video)])
    files, _ = watch.resolve_files(rec, folder, settings)
    assert files == [video.resolve()]


def test_partial_failure_never_ingests_markers(
    db: Session, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good, bad = tmp_path / "a.mp4", tmp_path / "b.mp4"
    good.write_bytes(b"x")
    bad.write_bytes(b"x")
    calls: list[int] = []

    def fake_pipeline(db, media, stages, settings, gate):  # type: ignore[no-untyped-def]
        if media.path.endswith("b.mp4"):
            raise StageFailedError("normalize", "falhou de propósito")
        normalized = SimpleNamespace(data={"probe": {"duration_s": 1.0}, "media": str(good)})
        return SimpleNamespace(results={"normalize": normalized})

    monkeypatch.setattr(service, "run_pipeline", fake_pipeline)

    def fake_markers(*args: object, **kwargs: object) -> MarkerReport:
        calls.append(1)
        return MarkerReport()

    monkeypatch.setattr(service, "ingest_markers", fake_markers)
    report = service.ingest_files(db, "origem", [good, bad], settings, AlwaysFreeGate())
    assert not report.ok and calls == []
    assert any("marcadores não atualizados" in w for w in report.markers.warnings)


def test_a15_truncated_ffprobe_json_is_a_failure_not_a_crash(
    tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    from cronista.ingest import ffmpeg

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout='{"streams": [', stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    assert ffmpeg.probe_media(settings, video).interrupted is True
    assert ffmpeg.probe_chapters(settings, video) == []


class _BusyGate:
    """Gate ocupado por um motivo fixo."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def is_free(self) -> bool:
        return False

    def reason(self) -> str:
        return self._reason


def test_a13_open_journal_is_not_abandoned_while_obs_still_records(
    db: Session, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O `mtime` pode estar defasado no Windows: com o OBS ainda gravando, não é abandono."""
    import os
    import time

    from cronista.ingest.journal import JournalWriter, Stamp
    from cronista.pipeline.gpu import OBS_RECORDING_REASON

    video = tmp_path / "longa.mp4"
    video.write_bytes(b"x")
    journal = tmp_path / "g1.markers.jsonl"
    t0 = time.time() - 7200
    with JournalWriter(journal) as writer:
        writer.recording_started(str(video), Stamp(100.0, datetime.fromtimestamp(t0, tz=UTC)))
    old = time.time() - 3600
    for path in (journal, video):
        os.utime(path, (old, old))
    later = lambda: time.time() + 5 * 3600  # noqa: E731

    ingested: list[int] = []
    monkeypatch.setattr(
        watch,
        "ingest_files",
        lambda *a, **k: (
            ingested.append(1) or SimpleNamespace(session_id=0, markers=MarkerReport(), ok=True, failures={})
        ),
    )

    recording = _BusyGate(OBS_RECORDING_REASON)
    assert watch.scan_once(db, settings, recording, tmp_path, "p", now=later) == []  # type: ignore[arg-type]
    assert ingested == []

    other = _BusyGate("jogo em tela cheia")  # outro motivo não prova que o OBS grava: vale o prazo
    (result,) = watch.scan_once(db, settings, other, tmp_path, "p", now=later)  # type: ignore[arg-type]
    assert result.abandoned and ingested == [1]
