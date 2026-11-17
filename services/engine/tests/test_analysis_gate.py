"""A análise respeita o gate de GPU (OBS gravando / jogo em tela cheia) e retoma depois de uma interrupção."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.audio import dsp
from cronista.audio.signals import signal_metas
from cronista.audio.stages import AudioSignalsStage
from cronista.config import Settings
from cronista.db.models import Job, MediaFile
from cronista.domain.models import StageResult
from cronista.pipeline import AlwaysFreeGate, Stage, StageContext, recover_orphans, run_pipeline
from cronista.pipeline.gpu import wait_until_free
from tests.test_pipeline import media  # noqa: F401  (fixture `media`)

RATE = 48000
BLOCK_S = 1.0


def write_tracks(folder: Path, seconds: int = 4) -> dict[str, str]:
    rng = np.random.default_rng(5)
    paths: dict[str, str] = {}
    for label in ("game", "mic"):
        path = folder / f"{label}.wav"
        sf.write(str(path), (rng.standard_normal(RATE * seconds) * 0.01).astype(np.float32), RATE)
        paths[label] = str(path)
    return paths


class BusyThenFree:
    """Gate que fica ocupado nas primeiras consultas feitas **durante** o processamento."""

    def __init__(self, busy_checks: int, interrupt_at: int | None = None) -> None:
        self.busy_left, self.checks, self.interrupt_at = busy_checks, 0, interrupt_at

    def is_free(self) -> bool:
        return True

    def is_free_while_working(self) -> bool:
        self.checks += 1
        if self.interrupt_at is not None and self.checks == self.interrupt_at:
            raise KeyboardInterrupt  # o processo morre no meio da etapa
        if self.busy_left > 0:
            self.busy_left -= 1
            return False
        return True


def test_analysis_blocks_while_the_gate_is_busy_and_checks_between_every_block(
    settings: Settings, tmp_path: Path
) -> None:
    gate = BusyThenFree(busy_checks=3)
    sleeps: list[float] = []

    def pause() -> None:
        wait_until_free(gate, 5.0, sleeps.append, working=True)

    ctx = StageContext(
        media_path=tmp_path / "m.mp4",
        out_dir=tmp_path,
        settings=settings,
        inputs={"audio": StageResult(data=write_tracks(tmp_path))},
        wait_for_gpu=pause,
    )
    result = AudioSignalsStage(dsp.DspParams(block_s=BLOCK_S)).run(ctx)

    assert sleeps == [5.0, 5.0, 5.0]  # esperou enquanto ocupado, no tempo de consulta configurado
    assert gate.checks >= 3 + 8  # 3 esperas + uma consulta por bloco (4 s de jogo + 4 s de microfone)
    assert set(signal_metas(result))  # e terminou normalmente depois que liberou


def test_killed_analysis_resumes_without_redoing_finished_stages(
    db: Session,
    media: MediaFile,  # noqa: F811
    settings: Settings,
    tmp_path: Path,
) -> None:
    calls: Counter[str] = Counter()

    class AudioFromDisk:
        name = "audio"
        version = "1"
        needs: tuple[str, ...] = ()
        uses_gpu = False

        def params(self, settings: Settings) -> dict[str, Any]:
            return {}

        def run(self, ctx: StageContext) -> StageResult:
            calls["audio"] += 1
            return StageResult(data=write_tracks(ctx.out_dir))

    stages: list[Stage] = [AudioFromDisk(), AudioSignalsStage(dsp.DspParams(block_s=BLOCK_S))]

    gate = BusyThenFree(busy_checks=0, interrupt_at=3)
    with pytest.raises(KeyboardInterrupt):
        run_pipeline(db, media, stages, settings, gate)
    job = db.scalars(select(Job).where(Job.media_file_id == media.id, Job.stage == "audio_signals")).one()
    assert job.status == "running"  # morreu no meio, sem terminar

    assert recover_orphans(db) == 1
    report = run_pipeline(db, media, stages, settings, AlwaysFreeGate())

    assert report.cached == ["audio"] and report.executed == ["audio_signals"]
    assert calls["audio"] == 1  # a etapa que já tinha terminado não foi refeita
    assert len(signal_metas(report.results["audio_signals"])) == 6
