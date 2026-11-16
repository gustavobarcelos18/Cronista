"""Gravador de marcadores: núcleo (OBS em memória), adaptador real contra o servidor falso e hotkeys."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.config import DEFAULT_HOTKEYS, Settings
from cronista.db.models import Marker
from cronista.domain.journal import MarkerPressed, RecordingStarted
from cronista.domain.models import MarkerKind
from cronista.domain.timeline import reconstruct_media_times
from cronista.ingest.journal import JournalWriter, Stamp, find_journals, read_journal
from cronista.ingest.service import ingest_folder
from cronista.pipeline import AlwaysFreeGate
from cronista.recorder.core import Recorder
from cronista.recorder.files import find_recording_file, newest_video
from cronista.recorder.hotkeys import HotkeyConfigError, resolve_hotkeys
from cronista.recorder.obs import SimpleObsLink
from cronista.recorder.ports import (
    STATE_PAUSED,
    STATE_RESUMED,
    STATE_STARTED,
    STATE_STOPPED,
    ObsError,
    ObsEvent,
    RecordFile,
    RecordState,
    RecordStatus,
)
from cronista.recorder.run import run_forever, run_session
from tests.conftest import needs_ffmpeg
from tests.fake_obs import running_fake_obs

BASE = datetime.now(UTC)


class FakeClock:
    """Relógio manual: `t` em segundos desde `BASE`, monotônico e UTC andam juntos."""

    def __init__(self, t: float = 100.0) -> None:
        self.t = t

    def __call__(self) -> Stamp:
        return self.at(self.t)

    @staticmethod
    def at(t: float) -> Stamp:
        return Stamp(t, BASE + timedelta(seconds=t - 100.0))


class FakeFeedback:
    def __init__(self) -> None:
        self.marked_calls: list[tuple[MarkerKind, str]] = []
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def marked(self, kind: MarkerKind, detail: str = "") -> None:
        self.marked_calls.append((kind, detail))

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def info(self, message: str) -> None:
        self.infos.append(message)


class MemoryLink:
    """OBS em memória: só o que o núcleo pede."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.chapters: list[str] = []
        self.status = RecordStatus(active=False, paused=False, duration_s=0.0)
        self.refuse_chapters = False
        self.directory_error = False

    async def connect(self) -> None: ...

    async def next_event(self) -> ObsEvent | None:
        return None

    async def record_status(self) -> RecordStatus:
        return self.status

    async def record_directory(self) -> str:
        if self.directory_error:
            raise ObsError("GetRecordDirectory: falhou")
        return str(self.directory)

    async def create_chapter(self, name: str) -> bool:
        if self.refuse_chapters:
            return False
        self.chapters.append(name)
        return True

    async def close(self) -> None: ...


def _started(t: float) -> RecordState:
    return RecordState(STATE_STARTED, None, FakeClock.at(t))


def _recorder(
    tmp_path: Path, settings: Settings, **kw: object
) -> tuple[Recorder, MemoryLink, FakeFeedback, FakeClock]:
    link = MemoryLink(tmp_path)
    feedback = FakeFeedback()
    clock = FakeClock()
    ids = iter(f"id{n}" for n in range(1, 100))

    async def no_sleep(_: float) -> None:
        return None

    recorder = Recorder(
        link,
        feedback,
        settings,
        clock=clock,
        new_id=lambda: next(ids),
        sleep=no_sleep,
        find_timeout_s=0.0,
        **kw,
    )
    return recorder, link, feedback, clock


def _journal(directory: Path) -> Path:
    (path,) = find_journals(directory)
    return path


# --- núcleo ---


def test_full_recording_writes_journal_and_chapters_with_the_right_times(
    tmp_path: Path, settings: Settings
) -> None:
    (tmp_path / "jogo.mp4").write_bytes(b"x")
    recorder, link, feedback, _ = _recorder(tmp_path, settings)

    async def scenario() -> None:
        await recorder.handle(_started(100.0))
        await recorder.press(MarkerKind.MOMENTO, FakeClock.at(105.0))
        await recorder.press(MarkerKind.NOVO_DIA, FakeClock.at(110.5))
        await recorder.handle(RecordState(STATE_PAUSED, None, FakeClock.at(112.0)))
        await recorder.handle(RecordState(STATE_RESUMED, None, FakeClock.at(120.0)))
        await recorder.press(MarkerKind.MORTE_FALHA, FakeClock.at(125.0))
        await recorder.handle(RecordState(STATE_STOPPED, str(tmp_path / "jogo.mp4"), FakeClock.at(130.0)))

    asyncio.run(scenario())

    assert link.chapters == ["momento|id1", "novo_dia|id2", "morte_falha|id3"]
    events, warnings = read_journal(_journal(tmp_path))
    assert warnings == []
    assert [e.type for e in events] == [
        "recording_started", "marker", "marker", "paused", "unpaused", "marker", "recording_stopped",
    ]  # fmt: skip
    rebuilt = reconstruct_media_times(events)
    assert [(m.kind, m.marker_id, m.file_name) for m in rebuilt.markers] == [
        (MarkerKind.MOMENTO, "id1", str(tmp_path / "jogo.mp4")),
        (MarkerKind.NOVO_DIA, "id2", str(tmp_path / "jogo.mp4")),
        (MarkerKind.MORTE_FALHA, "id3", str(tmp_path / "jogo.mp4")),
    ]
    # 105-100 = 5 s; 110,5-100 = 10,5 s; 125-100-8 s de pausa = 17 s
    assert [m.media_time_s for m in rebuilt.markers] == pytest.approx([5.0, 10.5, 17.0])
    assert [k for k, _ in feedback.marked_calls] == [
        MarkerKind.MOMENTO, MarkerKind.NOVO_DIA, MarkerKind.MORTE_FALHA,
    ]  # fmt: skip
    assert not recorder.recording


def test_press_outside_recording_is_ignored_with_a_warning(tmp_path: Path, settings: Settings) -> None:
    recorder, link, feedback, _ = _recorder(tmp_path, settings)
    asyncio.run(recorder.press(MarkerKind.MOMENTO, FakeClock.at(101.0)))
    assert link.chapters == [] and feedback.marked_calls == []
    assert "fora de gravação" in feedback.warnings[0]
    assert find_journals(tmp_path) == []


def test_construction_key_toggles_and_open_one_warns_at_stop(tmp_path: Path, settings: Settings) -> None:
    (tmp_path / "jogo.mp4").write_bytes(b"x")
    recorder, _, feedback, _ = _recorder(tmp_path, settings)

    async def scenario() -> None:
        await recorder.handle(_started(100.0))
        await recorder.press(MarkerKind.CONSTRUCAO, FakeClock.at(101.0))
        assert recorder.construction_open
        await recorder.press(MarkerKind.CONSTRUCAO, FakeClock.at(102.0))
        assert not recorder.construction_open
        await recorder.press(MarkerKind.CONSTRUCAO, FakeClock.at(103.0))
        await recorder.handle(RecordState(STATE_STOPPED, None, FakeClock.at(104.0)))

    asyncio.run(scenario())
    assert [d for k, d in feedback.marked_calls if k is MarkerKind.CONSTRUCAO] == ["início", "fim", "início"]
    assert any("construção ficou aberta" in w for w in feedback.warnings)


def test_chapter_refused_by_obs_keeps_the_journal_entry(tmp_path: Path, settings: Settings) -> None:
    (tmp_path / "jogo.mp4").write_bytes(b"x")
    recorder, link, feedback, _ = _recorder(tmp_path, settings)
    link.refuse_chapters = True

    async def scenario() -> None:
        await recorder.handle(_started(100.0))
        await recorder.press(MarkerKind.MOMENTO, FakeClock.at(101.0))

    asyncio.run(scenario())
    events, _ = read_journal(_journal(tmp_path))
    assert any(isinstance(e, MarkerPressed) for e in events)
    assert any("o diário tem o toque" in w for w in feedback.warnings)
    assert feedback.marked_calls  # o criador ainda ouve o "registrado"


def test_split_changes_the_file_for_later_markers(tmp_path: Path, settings: Settings) -> None:
    (tmp_path / "a.mp4").write_bytes(b"x")
    recorder, _, _, _ = _recorder(tmp_path, settings)

    async def scenario() -> None:
        await recorder.handle(_started(100.0))
        await recorder.press(MarkerKind.MOMENTO, FakeClock.at(110.0))
        await recorder.handle(RecordFile(str(tmp_path / "b.mp4"), FakeClock.at(150.0)))
        await recorder.press(MarkerKind.MOMENTO, FakeClock.at(160.0))

    asyncio.run(scenario())
    events, _ = read_journal(_journal(tmp_path))
    markers = reconstruct_media_times(events).markers
    assert [(Path(m.file_name).name, m.media_time_s) for m in markers] == [("a.mp4", 10.0), ("b.mp4", 10.0)]


def test_unknown_recording_file_is_journaled_with_empty_path_and_warns(
    tmp_path: Path, settings: Settings
) -> None:
    recorder, _, feedback, _ = _recorder(tmp_path, settings)  # pasta sem vídeo
    asyncio.run(recorder.handle(_started(100.0)))
    events, _ = read_journal(_journal(tmp_path))
    assert isinstance(events[0], RecordingStarted) and events[0].path == ""
    assert any("não achei o arquivo" in w for w in feedback.warnings)


def test_without_record_directory_the_chapter_is_still_created(tmp_path: Path, settings: Settings) -> None:
    recorder, link, feedback, _ = _recorder(tmp_path, settings)
    link.directory_error = True

    async def scenario() -> None:
        await recorder.handle(_started(100.0))
        await recorder.press(MarkerKind.MOMENTO, FakeClock.at(101.0))

    asyncio.run(scenario())
    assert link.chapters == ["momento|id1"]
    assert find_journals(tmp_path) == []
    assert any("sem diário" in w for w in feedback.warnings)


def test_presses_during_file_resolution_wait_and_keep_their_own_timestamp(
    tmp_path: Path, settings: Settings
) -> None:
    link = MemoryLink(tmp_path)
    feedback = FakeFeedback()
    ids = iter(["a", "b"])
    slept = 0

    async def slow_sleep(_: float) -> None:
        nonlocal slept
        slept += 1
        if slept == 2:  # o arquivo só aparece na segunda espera
            (tmp_path / "tarde.mp4").write_bytes(b"x")
        await asyncio.sleep(0)

    recorder = Recorder(
        link, feedback, settings, clock=FakeClock(), new_id=lambda: next(ids), sleep=slow_sleep
    )

    async def scenario() -> None:
        starting = asyncio.create_task(recorder.handle(_started(100.0)))
        await asyncio.sleep(0)
        press = asyncio.create_task(recorder.press(MarkerKind.MOMENTO, FakeClock.at(101.0)))
        await asyncio.gather(starting, press)

    asyncio.run(scenario())
    events, _ = read_journal(_journal(tmp_path))
    assert [e.type for e in events] == ["recording_started", "marker"]
    assert isinstance(events[0], RecordingStarted) and events[0].path.endswith("tarde.mp4")
    assert isinstance(events[1], MarkerPressed) and events[1].mono_s == 101.0


def test_attach_to_a_recording_already_running_backdates_the_start(
    tmp_path: Path, settings: Settings
) -> None:
    (tmp_path / "jogo.mp4").write_bytes(b"x")
    recorder, link, feedback, clock = _recorder(tmp_path, settings)
    link.status = RecordStatus(active=True, paused=False, duration_s=30.0)
    clock.t = 200.0

    async def scenario() -> None:
        await recorder.attach()
        await recorder.press(MarkerKind.MOMENTO, FakeClock.at(210.0))

    asyncio.run(scenario())
    events, _ = read_journal(_journal(tmp_path))
    assert isinstance(events[0], RecordingStarted) and events[0].mono_s == pytest.approx(170.0)
    assert reconstruct_media_times(events).markers[0].media_time_s == pytest.approx(40.0)
    assert any("já estava gravando" in w for w in feedback.warnings)


def test_restart_after_a_crash_reopens_the_same_journal_without_corrupting_it(
    tmp_path: Path, settings: Settings
) -> None:
    video = tmp_path / "jogo.mp4"
    video.write_bytes(b"x")
    with JournalWriter(tmp_path / "gravacao-antiga.markers.jsonl") as writer:
        writer.recording_started(str(video), FakeClock.at(100.0))
        writer.marker(MarkerKind.MOMENTO, "antes", FakeClock.at(105.0))
    with (tmp_path / "gravacao-antiga.markers.jsonl").open("ab") as handle:
        handle.write(b'{"type": "marker", "mono_s": 1')  # queda no meio de uma linha

    recorder, link, feedback, clock = _recorder(tmp_path, settings)
    link.status = RecordStatus(active=True, paused=False, duration_s=40.0)
    clock.t = 140.0

    async def scenario() -> None:
        await recorder.attach()
        await recorder.press(MarkerKind.NOVO_DIA, FakeClock.at(141.0))
        recorder.close()

    asyncio.run(scenario())
    (journal,) = find_journals(tmp_path)  # nenhum diário novo
    events, warnings = read_journal(journal)
    assert len(warnings) == 1  # só a linha cortada
    assert [e.type for e in events] == ["recording_started", "marker", "marker"]
    assert [m.marker_id for m in reconstruct_media_times(events).markers] == ["antes", "id1"]
    assert any("diário retomado" in w for w in feedback.warnings)


# --- achar o arquivo ---


def test_newest_video_ignores_old_and_non_video_files(tmp_path: Path) -> None:
    old = tmp_path / "velho.mp4"
    old.write_bytes(b"x")
    stale = (BASE - timedelta(hours=1)).timestamp()
    import os

    os.utime(old, (stale, stale))
    (tmp_path / "notas.txt").write_bytes(b"x")
    fresh = tmp_path / "novo.mkv"
    fresh.write_bytes(b"x")
    assert newest_video(tmp_path, [".mp4", ".mkv"], BASE) == fresh
    assert newest_video(tmp_path / "nao-existe", [".mp4"], BASE) is None


def test_find_recording_file_gives_up_after_the_timeout(tmp_path: Path) -> None:
    waits: list[float] = []

    async def record_sleep(seconds: float) -> None:
        waits.append(seconds)

    found = asyncio.run(
        find_recording_file(tmp_path, [".mp4"], BASE, timeout_s=1.0, poll_s=0.25, sleep=record_sleep)
    )
    assert found is None and len(waits) == 4


# --- adaptador real (simpleobsws) contra o servidor falso ---


def _link(port: int, password: str | None = None, clock: Callable[[], Stamp] | None = None) -> SimpleObsLink:
    return SimpleObsLink("127.0.0.1", port, password, clock or FakeClock(), identify_timeout_s=2.0)


def test_real_adapter_talks_the_protocol_and_receives_ordered_events(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with running_fake_obs(tmp_path) as obs:
            link = _link(obs.port)
            await link.connect()
            try:
                assert await link.record_directory() == str(tmp_path)
                assert (await link.record_status()).active is False

                await obs.start_recording()
                await obs.pause()
                await obs.resume()
                await obs.split(tmp_path / "b.mp4")
                await obs.stop_recording(tmp_path / "b.mp4")
                events = [await asyncio.wait_for(link.next_event(), 2) for _ in range(5)]
                assert [type(e) for e in events] == [RecordState] * 3 + [RecordFile, RecordState]
                states = [e.state for e in events if isinstance(e, RecordState)]
                assert states == [
                    "OBS_WEBSOCKET_OUTPUT_STARTED", STATE_PAUSED, STATE_RESUMED, STATE_STOPPED,
                ]  # fmt: skip
                last = events[-1]
                assert isinstance(last, RecordState) and last.output_path == str(tmp_path / "b.mp4")

                await obs.start_recording()
                assert await link.create_chapter("momento|x1") is True
                assert obs.chapters == ["momento|x1"]
                obs.fail_chapters = True
                assert await link.create_chapter("momento|x2") is False
            finally:
                await link.close()

    asyncio.run(scenario())


def test_real_adapter_authenticates_and_rejects_a_wrong_password(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with running_fake_obs(tmp_path, password="segredo") as obs:
            good = _link(obs.port, "segredo")
            await good.connect()
            assert await good.record_directory() == str(tmp_path)
            await good.close()

            bad = _link(obs.port, "errada")
            with pytest.raises(ObsError, match="senha"):
                await bad.connect()

    asyncio.run(scenario())


def test_real_adapter_reports_connection_refused() -> None:
    async def scenario() -> None:
        link = _link(1)  # porta 1: ninguém escuta
        with pytest.raises(ObsError):
            await link.connect()

    asyncio.run(scenario())


def test_recorder_end_to_end_against_the_fake_obs(tmp_path: Path, settings: Settings) -> None:
    video = tmp_path / "jogo.mp4"

    async def scenario() -> None:
        async with running_fake_obs(tmp_path) as obs:
            clock = FakeClock()
            link = _link(obs.port, clock=clock)
            await link.connect()
            feedback = FakeFeedback()
            recorder = Recorder(link, feedback, settings, clock=clock)
            session = asyncio.create_task(run_session(recorder, link))

            video.write_bytes(b"x")
            await obs.start_recording()
            await _until(lambda: recorder.recording)
            await recorder.press(MarkerKind.MOMENTO, clock())
            await recorder.press(MarkerKind.NOVO_DIA, clock())
            await obs.stop_recording(video)
            await _until(lambda: not recorder.recording)

            assert [c.split("|")[0] for c in obs.chapters] == ["momento", "novo_dia"]
            assert all(len(c.split("|")[1]) == 8 for c in obs.chapters)  # id aleatório de 4 bytes em hex

            await obs.drop_connections()
            await asyncio.wait_for(session, 3)  # conexão caída encerra a sessão
            await link.close()

    asyncio.run(scenario())
    events, _ = read_journal(_journal(tmp_path))
    assert [e.type for e in events] == ["recording_started", "marker", "marker", "recording_stopped"]


async def _until(condition: Callable[[], bool], timeout_s: float = 3.0) -> None:
    async def poll() -> None:
        while not condition():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), timeout_s)


class FakeHotkeys:
    def __init__(self) -> None:
        self.on_press: Callable[[MarkerKind], None] | None = None
        self.stopped = False

    def start(self, on_press: Callable[[MarkerKind], None]) -> None:
        self.on_press = on_press

    def stop(self) -> None:
        self.stopped = True


def test_run_forever_presses_flow_to_obs_and_it_reconnects_after_a_drop(
    tmp_path: Path, settings: Settings
) -> None:
    (tmp_path / "jogo.mp4").write_bytes(b"x")
    hotkeys = FakeHotkeys()

    async def scenario() -> None:
        async with running_fake_obs(tmp_path) as obs:
            cfg = settings.model_copy(update={"obs_port": obs.port, "obs_host": "127.0.0.1"})
            runner = asyncio.create_task(run_forever(cfg, FakeFeedback(), hotkeys=hotkeys, retry_s=0.05))
            await _until(lambda: bool(obs._connections))
            await obs.start_recording()
            await asyncio.sleep(0.4)  # deixa o gravador resolver o arquivo e abrir o diário

            assert hotkeys.on_press is not None
            hotkeys.on_press(MarkerKind.MOMENTO)
            await _until(lambda: len(obs.chapters) == 1)

            await obs.drop_connections()
            await _until(lambda: not obs._connections)
            await _until(lambda: bool(obs._connections))  # reconectou
            await _until(lambda: obs.requests.count("GetRecordStatus") >= 2)  # reassumiu a gravação

            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(scenario())
    assert hotkeys.stopped


# --- hotkeys e config ---


def test_default_hotkeys_are_valid_and_cover_every_kind() -> None:
    keys = resolve_hotkeys(dict(DEFAULT_HOTKEYS))
    assert set(keys) == set(MarkerKind)


def test_partial_hotkey_config_keeps_the_other_defaults(tmp_path: Path) -> None:
    custom = Settings(env="t", data_dir=tmp_path, marker_hotkeys={"momento": "<ctrl>+<alt>+m"})
    assert custom.marker_hotkeys["momento"] == "<ctrl>+<alt>+m"
    assert custom.marker_hotkeys["novo_dia"] == "<f14>"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"nao_existe": "<f1>"}, "tipo desconhecido"),
        ({"momento": None}, "obrigatória"),
        ({"novo_dia": None}, "obrigatória"),
        ({"conquista": "<f13>"}, "mesma tecla"),
    ],
)
def test_hotkey_config_errors_are_clear(override: dict[str, str | None], message: str) -> None:
    with pytest.raises(HotkeyConfigError, match=message):
        resolve_hotkeys({**DEFAULT_HOTKEYS, **override})


def test_optional_hotkeys_can_be_disabled() -> None:
    keys = resolve_hotkeys({**DEFAULT_HOTKEYS, "cinematica": None, "foto_progresso": None})
    assert MarkerKind.CINEMATICA not in keys


@pytest.mark.skipif(sys.platform != "win32", reason="pynput só é instalado no Windows")
def test_default_hotkey_syntax_is_accepted_by_pynput() -> None:
    from pynput import keyboard

    for combo in DEFAULT_HOTKEYS.values():
        assert combo is not None
        assert keyboard.HotKey.parse(combo)


# --- ingestão com arquivo desconhecido ---


@needs_ffmpeg
def test_ingest_assumes_the_first_file_when_the_journal_has_no_path(
    db: Session, settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    folder = tmp_path / "s"
    folder.mkdir()
    shutil.copy(next(fixture_folders["normal"].iterdir()), folder / "gravacao.mp4")
    clock = iter([10.0, 10.5, 11.5])
    with JournalWriter(folder / "g.markers.jsonl", mono=lambda: next(clock), utc=lambda: BASE) as writer:
        writer.recording_started("")  # o gravador não achou o arquivo
        writer.marker(MarkerKind.NOVO_DIA, "d1")
        writer.marker(MarkerKind.MOMENTO, "m1")

    report = ingest_folder(db, folder, settings, AlwaysFreeGate(), "p")
    assert report.ok
    rows = list(db.scalars(select(Marker).order_by(Marker.media_time_s)))
    assert [(r.kind, r.source, round(r.media_time_s, 1)) for r in rows] == [
        ("novo_dia", "journal", 0.5),
        ("momento", "journal", 1.5),
    ]
    assert any("assumido 'gravacao.mp4'" in w for w in report.markers.warnings)


def test_journal_lines_are_plain_json(tmp_path: Path) -> None:
    with JournalWriter(tmp_path / "x.markers.jsonl") as writer:
        writer.marker(MarkerKind.MOMENTO, "m", FakeClock.at(1.0))
    line = (tmp_path / "x.markers.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads(line)["mono_s"] == 1.0
