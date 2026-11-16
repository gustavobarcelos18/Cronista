"""Gates de GPU (sinais injetados), o gate do OBS contra o servidor falso e a pausa no meio da etapa."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from cronista.config import Settings
from cronista.db.models import MediaFile
from cronista.domain.models import StageResult
from cronista.gates import (
    CachedGate,
    CompositeGate,
    FullscreenGate,
    GpuLoadGate,
    ObsRecordingGate,
    build_gate,
)
from cronista.pipeline import (
    AlwaysFreeGate,
    StageContext,
    gate_reason,
    is_free_now,
    run_pipeline,
    wait_until_free,
)
from tests.fake_obs import FakeObs, running_fake_obs
from tests.test_pipeline import media as media


@pytest.mark.parametrize(
    ("state", "free"), [(5, True), (7, True), (None, True), (2, False), (3, False), (4, False)]
)
def test_fullscreen_gate_states(state: int | None, free: bool) -> None:
    gate = FullscreenGate(lambda: state)
    assert gate.is_free() is free
    assert (gate.reason() is None) is free


@pytest.mark.parametrize(("usage", "free"), [(None, True), (10, True), (59, True), (60, False), (99, False)])
def test_gpu_load_gate_threshold(usage: int | None, free: bool) -> None:
    gate = GpuLoadGate(60, lambda: usage)
    assert gate.is_free() is free
    assert (gate.reason() is None) is free


def test_composite_is_free_only_when_all_are_and_explains_the_first_block() -> None:
    free, fullscreen, loaded = (
        FullscreenGate(lambda: 5),
        FullscreenGate(lambda: 3),
        GpuLoadGate(10, lambda: 90),
    )
    assert CompositeGate([free, free]).is_free()

    gate = CompositeGate([free, fullscreen, loaded])
    assert not gate.is_free()
    reason = gate_reason(gate)
    assert reason is not None and "tela cheia" in reason  # o primeiro que recusou, não o da GPU

    assert gate_reason(CompositeGate([free])) is None
    assert gate_reason(AlwaysFreeGate()) is None


def test_build_gate_follows_the_environment(tmp_path: Path) -> None:
    dev = Settings(env="dev", data_dir=tmp_path)
    assert isinstance(build_gate(dev), AlwaysFreeGate)

    prod = Settings(env="prod", data_dir=tmp_path, gpu_gate=True)
    gate = build_gate(prod)
    assert isinstance(gate, CachedGate) and isinstance(gate._inner, CompositeGate)
    assert len(gate._inner._gates) == 2

    with_load = Settings(env="prod", data_dir=tmp_path, gpu_gate=True, gpu_busy_percent=70)
    gate = build_gate(with_load)
    assert isinstance(gate, CachedGate) and isinstance(gate._inner, CompositeGate)
    assert len(gate._inner._gates) == 3


def test_wait_until_free_counts_waits_and_logs_the_reason() -> None:
    class Flaky:
        def __init__(self) -> None:
            self.left = 2

        def is_free(self) -> bool:
            self.left -= 1
            return self.left < 0

        def reason(self) -> str:
            return "jogo aberto"

    naps: list[float] = []
    assert wait_until_free(Flaky(), 7.0, naps.append, stage="x") == 2
    assert naps == [7.0, 7.0]


# --- gate do OBS contra o servidor falso (em outra thread: o gate é síncrono) ---


@contextmanager
def fake_obs_thread(record_dir: Path, password: str | None = None) -> Iterator[FakeObs]:
    ready = threading.Event()
    stop = threading.Event()
    holder: list[FakeObs] = []

    def run() -> None:
        async def main() -> None:
            async with running_fake_obs(record_dir, password) as fake:
                holder.append(fake)
                ready.set()
                while not stop.is_set():
                    await asyncio.sleep(0.02)

        asyncio.run(main())

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert ready.wait(5)
    try:
        yield holder[0]
    finally:
        stop.set()
        thread.join(5)


def test_obs_gate_is_busy_only_while_obs_records(tmp_path: Path) -> None:
    with fake_obs_thread(tmp_path) as obs:
        gate = ObsRecordingGate("127.0.0.1", obs.port, None)
        assert gate.is_free() and gate.reason() is None

        obs.recording = True
        assert not gate.is_free()
        assert gate.reason() == "OBS gravando"

        obs.recording = False
        assert gate.is_free()


def test_obs_gate_is_free_when_obs_is_closed(tmp_path: Path) -> None:
    with fake_obs_thread(tmp_path) as obs:
        port = obs.port
    gate = ObsRecordingGate("127.0.0.1", port, None)  # o servidor já fechou
    assert gate.is_free()


def test_obs_gate_authenticates_with_the_configured_password(tmp_path: Path) -> None:
    with fake_obs_thread(tmp_path, password="segredo") as obs:
        obs.recording = True
        assert not ObsRecordingGate("127.0.0.1", obs.port, "segredo").is_free()


# --- pausa no meio de uma etapa longa ---


def test_gpu_stage_can_pause_between_chunks(db: Session, media: MediaFile, settings: Settings) -> None:
    log: list[str] = []

    class Chunked:
        name, version, uses_gpu = "chunked", "1", True
        needs: tuple[str, ...] = ()

        def params(self, settings: Settings) -> dict[str, object]:
            return {}

        def run(self, ctx: StageContext) -> StageResult:
            for chunk in range(3):
                ctx.wait_for_gpu()  # entre os blocos
                log.append(f"bloco{chunk}")
            return StageResult()

    class GameOpensAfterFirstChunk:
        def __init__(self) -> None:
            self.checks = 0

        def is_free(self) -> bool:
            self.checks += 1
            # 1ª consulta (antes da etapa) e a do bloco 0: livre. O jogo abre; fica ocupada por 2 consultas.
            return self.checks <= 2 or self.checks > 4

    naps: list[float] = []

    def sleep(seconds: float) -> None:
        log.append("espera")
        naps.append(seconds)

    run_pipeline(db, media, [Chunked()], settings, GameOpensAfterFirstChunk(), sleep=sleep)
    assert log == ["bloco0", "espera", "espera", "bloco1", "bloco2"]


def test_load_gate_never_blocks_a_stage_that_is_already_working(
    db: Session, media: MediaFile, settings: Settings
) -> None:
    """A carga da GPU medida no meio da etapa é a da própria etapa: não pode fazê-la esperar por si mesma."""
    readings = iter([5, 95, 95, 95, 95])  # livre ao começar; depois a própria etapa carrega a GPU
    gate = CompositeGate([GpuLoadGate(60, lambda: next(readings))])
    log: list[str] = []

    class Chunked:
        name, version, uses_gpu = "chunked", "1", True
        needs: tuple[str, ...] = ()

        def params(self, settings: Settings) -> dict[str, object]:
            return {}

        def run(self, ctx: StageContext) -> StageResult:
            for chunk in range(3):
                ctx.wait_for_gpu()
                log.append(f"bloco{chunk}")
            return StageResult()

    naps: list[float] = []
    run_pipeline(db, media, [Chunked()], settings, gate, sleep=naps.append)
    assert log == ["bloco0", "bloco1", "bloco2"] and naps == []


def test_composite_working_check_skips_only_the_signals_the_work_causes() -> None:
    loaded = GpuLoadGate(10, lambda: 90)
    fullscreen = FullscreenGate(lambda: 3)
    assert not CompositeGate([loaded]).is_free()
    assert CompositeGate([loaded]).is_free_while_working()
    assert not CompositeGate([loaded, fullscreen]).is_free_while_working()  # o jogo continua valendo


def test_is_free_now_falls_back_to_is_free_for_simple_gates() -> None:
    class Simple:
        def is_free(self) -> bool:
            return False

    assert not is_free_now(Simple(), working=True)
    assert not is_free_now(Simple(), working=False)


def test_cached_gate_reuses_the_answer_within_the_ttl() -> None:
    clock = [0.0]
    calls: list[str] = []

    class Inner:
        def is_free(self) -> bool:
            calls.append("full")
            return True

        def is_free_while_working(self) -> bool:
            calls.append("work")
            return True

    gate = CachedGate(Inner(), 3.0, now=lambda: clock[0])
    assert gate.is_free() and gate.is_free() and gate.is_free_while_working() and gate.is_free_while_working()
    assert calls == ["full", "work"]  # um por tipo de consulta

    clock[0] = 2.9
    gate.is_free()
    assert calls == ["full", "work"]
    clock[0] = 3.1  # TTL vencido (menor que o intervalo de espera de 5 s)
    gate.is_free()
    assert calls == ["full", "work", "full"]


def test_cached_gate_forwards_the_reason() -> None:
    gate = CachedGate(FullscreenGate(lambda: 3), 3.0)
    assert not gate.is_free()
    assert gate_reason(gate) is not None


def test_obs_gate_warns_in_the_log_when_the_password_is_wrong(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    with fake_obs_thread(tmp_path, password="segredo") as obs:
        obs.recording = True
        with caplog.at_level(logging.WARNING, logger="cronista"):
            gate = ObsRecordingGate("127.0.0.1", obs.port, "errada")
            assert gate.is_free()  # sem enxergar a gravação, não bloqueia...
    assert any(r.getMessage() == "gate_obs_recusou_conexao" for r in caplog.records)  # ...mas avisa
