"""Serviço que observa a pasta do OBS e ingere cada gravação quando ela termina."""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista import watch
from cronista.config import Settings
from cronista.db.models import Artifact, Marker, Project, RecordingSession
from cronista.domain.models import MarkerKind
from cronista.ingest.journal import JournalWriter, Stamp
from cronista.ingest.service import SessionConflictError, ingest_files, ingest_folder
from cronista.pipeline import AlwaysFreeGate
from cronista.watch import Failure, Processed, scan_once, serve
from tests.conftest import needs_ffmpeg

pytestmark = needs_ffmpeg

T0 = time.time() - 7200  # a gravação de mentira começou há duas horas


def stamp(t: float) -> Stamp:
    """Instante `t` (mono = t; UTC alinhado a T0 + t - 100)."""
    return Stamp(t, datetime.fromtimestamp(T0 + t - 100.0, UTC))


def put_video(folder: Path, fixtures: dict[str, Path], variant: str, name: str, mtime_t: float) -> Path:
    source = sorted(fixtures[variant].iterdir())
    target = folder / name
    shutil.copy(source[0], target)
    os.utime(target, (T0 + mtime_t - 100.0, T0 + mtime_t - 100.0))
    return target


def write_journal(
    folder: Path,
    name: str,
    path: str,
    markers: list[tuple[MarkerKind, str, float]],
    *,
    stop_at: float | None = 110.0,
    changes: list[tuple[str, float]] | None = None,
) -> Path:
    journal = folder / f"{name}.markers.jsonl"
    with JournalWriter(journal) as writer:
        writer.recording_started(path, stamp(100.0))
        writes: list[tuple[float, Callable[[], None]]] = []
        for kind, marker_id, when in markers:
            writes.append((when, partial(writer.marker, kind, marker_id, stamp(when))))
        for new_path, when in changes or []:
            writes.append((when, partial(writer.file_changed, new_path, stamp(when))))
        for _, write in sorted(writes, key=lambda item: item[0]):
            write()
        if stop_at is not None:
            writer.recording_stopped(stamp(stop_at))
    return journal


def settle(journal: Path, folder: Path) -> None:
    """Deixa tudo na pasta velho o bastante para o serviço considerar parado."""
    old = time.time() - 3600
    for path in [journal, *folder.iterdir()]:
        os.utime(path, (old, old))


def sessions(db: Session) -> list[RecordingSession]:
    return list(db.scalars(select(RecordingSession).order_by(RecordingSession.id)))


def markers_of(db: Session, session: RecordingSession) -> list[tuple[str, str]]:
    rows = db.scalars(select(Marker).where(Marker.session_id == session.id).order_by(Marker.media_time_s))
    return [(r.kind, r.marker_id) for r in rows]


def scan(db: Session, settings: Settings, folder: Path, **kw: object) -> list[Processed]:
    return scan_once(db, settings, AlwaysFreeGate(), folder, "p", **kw)  # type: ignore[arg-type]


def test_finished_recording_is_ingested_once(
    db: Session, settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    folder = tmp_path / "obs"
    folder.mkdir()
    video = put_video(folder, fixture_folders, "normal", "jogo.mp4", 105.0)
    journal = write_journal(folder, "g1", str(video), [(MarkerKind.NOVO_DIA, "d1", 100.5)])
    settle(journal, folder)

    first = scan(db, settings, folder)
    assert len(first) == 1 and first[0].error is None
    (session,) = sessions(db)
    assert session.folder == str(journal.resolve())  # a origem é o diário
    assert markers_of(db, session) == [("novo_dia", "d1")]

    assert scan(db, settings, folder) == []  # já ingerida: não repete


def test_recording_is_not_ingested_before_it_stops_or_settles(
    db: Session, settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    folder = tmp_path / "obs"
    folder.mkdir()
    video = put_video(folder, fixture_folders, "normal", "jogo.mp4", 105.0)
    journal = write_journal(folder, "g1", str(video), [], stop_at=None)  # ainda gravando
    settle(journal, folder)
    assert scan(db, settings, folder) == []  # diário aberto, arquivo parado há 1 h < 4 h

    with JournalWriter(journal) as writer:
        writer.recording_stopped(stamp(110.0))
    # Acabou de parar: o arquivo/diário foram mexidos agora, falta o tempo de assentar.
    assert scan(db, settings, folder) == []
    assert len(scan(db, settings, folder, now=lambda: time.time() + 60)) == 1


def test_recordings_sharing_one_folder_become_separate_sessions(
    db: Session, settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    folder = tmp_path / "obs"
    folder.mkdir()
    a = put_video(folder, fixture_folders, "normal", "a.mp4", 105.0)
    b = put_video(folder, fixture_folders, "split", "b.mp4", 105.0)
    ja = write_journal(folder, "g1", str(a), [(MarkerKind.NOVO_DIA, "da", 100.5)])
    jb = write_journal(folder, "g2", str(b), [(MarkerKind.MOMENTO, "mb", 100.5)])
    settle(ja, folder)
    settle(jb, folder)

    results = scan(db, settings, folder)
    assert [r.error for r in results] == [None, None]
    first, second = sessions(db)
    assert [Path(m.path).name for m in first.media_files] == ["a.mp4"]
    assert [Path(m.path).name for m in second.media_files] == ["b.mp4"]
    assert ("momento", "mb") in markers_of(db, second)
    assert ("momento", "mb") not in markers_of(db, first)
    assert not any("não está nesta sessão" in w for r in results for w in r.warnings)


def test_split_recording_is_one_session_with_both_files(
    db: Session, settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    folder = tmp_path / "obs"
    folder.mkdir()
    one = put_video(folder, fixture_folders, "split", "p1.mp4", 105.0)
    two = shutil.copy(sorted(fixture_folders["split"].iterdir())[1], folder / "p2.mp4")
    journal = write_journal(
        folder, "g1", str(one), [(MarkerKind.NOVO_DIA, "d1", 100.5), (MarkerKind.MOMENTO, "m2", 106.0)],
        changes=[(str(two), 105.0)],
    )  # fmt: skip
    settle(journal, folder)

    (result,) = scan(db, settings, folder)
    assert result.error is None
    (session,) = sessions(db)
    assert [Path(m.path).name for m in session.media_files] == ["p1.mp4", "p2.mp4"]
    assert ("momento", "m2") in markers_of(db, session)


def test_unknown_first_file_is_deduced_from_modification_dates(
    db: Session, settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    folder = tmp_path / "obs"
    folder.mkdir()
    put_video(folder, fixture_folders, "split", "primeiro.mp4", 130.0)
    segundo = shutil.copy(sorted(fixture_folders["split"].iterdir())[1], folder / "segundo.mp4")
    os.utime(segundo, (T0 + 190.0 - 100.0, T0 + 190.0 - 100.0))
    put_video(folder, fixture_folders, "normal", "antigo-de-ontem.mp4", -50000.0)  # fora da janela
    journal = write_journal(folder, "g1", "", [], changes=[(str(segundo), 150.0)], stop_at=200.0)
    settle(journal, folder)
    for name, t in (("primeiro.mp4", 130.0), ("segundo.mp4", 190.0), ("antigo-de-ontem.mp4", -50000.0)):
        os.utime(folder / name, (T0 + t - 100.0, T0 + t - 100.0))

    (result,) = scan(db, settings, folder, now=lambda: time.time() + 1)
    assert result.error is None
    assert any("deduzido pela data: primeiro.mp4" in w for w in result.warnings)
    (session,) = sessions(db)
    assert [Path(m.path).name for m in session.media_files] == ["primeiro.mp4", "segundo.mp4"]


def test_abandoned_open_journal_is_ingested_as_interrupted(
    db: Session, settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    folder = tmp_path / "obs"
    folder.mkdir()
    video = put_video(folder, fixture_folders, "interrompida", "queda.mp4", 105.0)
    journal = write_journal(folder, "g1", str(video), [(MarkerKind.NOVO_DIA, "d1", 100.5)], stop_at=None)
    settle(journal, folder)

    assert scan(db, settings, folder) == []  # há 1 h: ainda pode ser uma pausa longa
    (result,) = scan(db, settings, folder, now=lambda: time.time() + 5 * 3600)
    assert result.abandoned and result.error is None
    assert any("tratada como interrompida" in w for w in result.warnings)
    (session,) = sessions(db)
    assert len(session.media_files) == 1


def test_failure_is_reported_once_then_retried_with_growing_backoff(
    db: Session, settings: Settings, tmp_path: Path
) -> None:
    folder = tmp_path / "obs"
    folder.mkdir()
    journal = write_journal(folder, "g1", str(folder / "sumiu.mp4"), [])
    settle(journal, folder)
    failed: dict[Path, Failure] = {}
    t0 = time.time()

    (first,) = scan(db, settings, folder, failed=failed, now=lambda: t0)
    assert first.error and "nenhum arquivo" in first.error
    assert scan(db, settings, folder, failed=failed, now=lambda: t0 + 599) == []  # antes do prazo: nada
    assert len(scan(db, settings, folder, failed=failed, now=lambda: t0 + 601)) == 1  # prazo de 600 s
    # A 2ª falha dobra o prazo (1200 s): 601 + 600 ainda não basta.
    assert scan(db, settings, folder, failed=failed, now=lambda: t0 + 1300) == []
    assert len(scan(db, settings, folder, failed=failed, now=lambda: t0 + 601 + 1201)) == 1
    assert failed[journal].attempts == 3


def test_failed_journal_is_retried_at_once_when_it_grows(
    db: Session, settings: Settings, tmp_path: Path
) -> None:
    folder = tmp_path / "obs"
    folder.mkdir()
    journal = write_journal(folder, "g1", str(folder / "sumiu.mp4"), [])
    settle(journal, folder)
    failed: dict[Path, Failure] = {}
    scan(db, settings, folder, failed=failed)
    assert scan(db, settings, folder, failed=failed) == []

    with JournalWriter(journal) as writer:  # o diário ganhou eventos (uma nova parada, como o gravador faria)
        writer.marker(MarkerKind.MOMENTO, "novo", stamp(105.0))
        writer.recording_stopped(stamp(111.0))
    settle(journal, folder)
    assert len(scan(db, settings, folder, failed=failed)) == 1


def test_unexpected_error_in_one_journal_does_not_stop_the_scan(
    db: Session,
    settings: Settings,
    fixture_folders: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = tmp_path / "obs"
    folder.mkdir()
    gone = write_journal(folder, "g1", str(folder / "a.mp4"), [])
    good_video = put_video(folder, fixture_folders, "normal", "b.mp4", 105.0)
    good = write_journal(folder, "g2", str(good_video), [])
    settle(gone, folder)
    settle(good, folder)

    real = watch.resolve_files

    def flaky(rec: watch.Recording, directory: Path, cfg: Settings) -> tuple[list[Path], list[str]]:
        if rec.journal == gone:
            return [folder / "sumiu-entre-listar-e-ler.mp4"], []  # `stat()` vai falhar
        return real(rec, directory, cfg)

    monkeypatch.setattr(watch, "resolve_files", flaky)
    results = scan(db, settings, folder)
    by_journal = {r.journal.name: r for r in results}
    assert by_journal["g1.markers.jsonl"].error and "erro inesperado" in by_journal["g1.markers.jsonl"].error
    assert by_journal["g2.markers.jsonl"].error is None  # o outro diário foi ingerido normalmente


def test_database_error_is_rolled_back_so_the_session_stays_usable(
    db: Session,
    settings: Settings,
    fixture_folders: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = tmp_path / "obs"
    folder.mkdir()
    video = put_video(folder, fixture_folders, "normal", "a.mp4", 105.0)
    settle(write_journal(folder, "g1", str(video), []), folder)

    def broken(*_: object, **__: object) -> object:
        db.add(Project(name="meio-da-transacao"))  # pendente quando o erro acontece
        raise RuntimeError("banco indisponível")

    monkeypatch.setattr(watch, "ingest_files", broken)
    with patch.object(db, "rollback", wraps=db.rollback) as rollback:
        (result,) = scan(db, settings, folder)
    assert result.error == "banco indisponível"
    rollback.assert_called()
    assert not db.new  # nada pendente: a Session continua utilizável nas próximas varreduras


def test_file_already_in_another_session_is_a_clear_error_not_an_empty_session(
    db: Session, settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    folder = tmp_path / "obs"
    folder.mkdir()
    video = put_video(folder, fixture_folders, "normal", "jogo.mp4", 105.0)
    journal = write_journal(folder, "g1", str(video), [])
    settle(journal, folder)
    manual = ingest_folder(db, folder, settings, AlwaysFreeGate(), "p")  # a pasta do OBS ingerida à mão
    assert manual.ok

    failed: dict[Path, Failure] = {}
    (result,) = scan(db, settings, folder, failed=failed)
    assert result.error and "já pertence à sessão" in result.error
    assert len(sessions(db)) == 1  # nenhuma sessão oca criada
    assert scan(db, settings, folder, failed=failed) == []  # e nada de laço de reingestão a cada varredura


def test_ingest_files_checks_conflicts_before_creating_anything(
    db: Session, settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    folder = tmp_path / "obs"
    folder.mkdir()
    video = put_video(folder, fixture_folders, "normal", "jogo.mp4", 105.0)
    ingest_folder(db, folder, settings, AlwaysFreeGate(), "p")
    with pytest.raises(SessionConflictError, match=r"jogo\.mp4"):
        ingest_files(db, "outra-origem", [video], settings, AlwaysFreeGate(), "outro-projeto")
    assert len(sessions(db)) == 1
    assert db.scalar(select(Project).where(Project.name == "outro-projeto")) is None


def test_journal_that_grows_after_an_abandoned_ingestion_is_ingested_again(
    db: Session, settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    folder = tmp_path / "obs"
    folder.mkdir()
    video = put_video(folder, fixture_folders, "interrompida", "queda.mp4", 105.0)
    journal = write_journal(folder, "g1", str(video), [(MarkerKind.NOVO_DIA, "d1", 100.5)], stop_at=None)
    settle(journal, folder)
    (first,) = scan(db, settings, folder, now=lambda: time.time() + 5 * 3600)
    assert first.abandoned and first.error is None
    (session,) = sessions(db)
    assert markers_of(db, session) == [("novo_dia", "d1")]
    assert scan(db, settings, folder, now=lambda: time.time() + 5 * 3600) == []  # nada mudou: não repete

    # O OBS só estava parado há horas: o criador retoma, marca e encerra; o arquivo termina de verdade.
    shutil.copy(sorted(fixture_folders["normal"].iterdir())[0], video)
    with JournalWriter(journal) as writer:
        writer.marker(MarkerKind.MOMENTO, "depois", stamp(101.0))
        writer.recording_stopped(stamp(110.0))
    settle(journal, folder)

    (again,) = scan(db, settings, folder)
    assert again.error is None and not again.abandoned
    assert again.session_id == session.id and len(sessions(db)) == 1
    assert ("momento", "depois") in markers_of(db, session)
    assert scan(db, settings, folder) == []


def test_serve_reports_an_unreachable_watch_dir_once(
    db: Session, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object, **__: object) -> list[Processed]:
        raise OSError("disco desconectado")

    monkeypatch.setattr(watch, "scan_once", broken)
    reported: list[Processed] = []
    serve(db, settings, AlwaysFreeGate(), tmp_path, "p", reported.append, max_scans=3, sleep=lambda _: None)
    assert [r.error for r in reported] == ["varredura falhou: disco desconectado"]


def test_incomplete_session_is_resumed(
    db: Session, settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    folder = tmp_path / "obs"
    folder.mkdir()
    video = put_video(folder, fixture_folders, "normal", "jogo.mp4", 105.0)
    settle(write_journal(folder, "g1", str(video), []), folder)
    scan(db, settings, folder)
    (before,) = sessions(db)

    for artifact in db.scalars(select(Artifact).where(Artifact.stage == "audio")):
        db.delete(artifact)  # como se o processo tivesse morrido antes da última etapa
    db.commit()

    (again,) = scan(db, settings, folder)
    assert again.session_id == before.id and again.error is None
    assert len(sessions(db)) == 1


def test_serve_loop_scans_repeatedly_and_reports_each_recording_once(
    db: Session, settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    folder = tmp_path / "obs"
    folder.mkdir()
    video = put_video(folder, fixture_folders, "normal", "jogo.mp4", 105.0)
    settle(write_journal(folder, "g1", str(video), []), folder)
    reported: list[Processed] = []
    naps: list[float] = []

    serve(db, settings, AlwaysFreeGate(), folder, "p", reported.append, max_scans=3, sleep=naps.append)
    assert len(reported) == 1
    assert naps == [settings.watch_poll_seconds] * 2


def test_manual_folder_ingest_still_uses_the_folder_as_origin(
    db: Session, settings: Settings, fixture_folders: dict[str, Path]
) -> None:
    from cronista.ingest.service import ingest_folder

    ingest_folder(db, fixture_folders["normal"], settings, AlwaysFreeGate(), "p")
    (session,) = sessions(db)
    assert session.folder == str(fixture_folders["normal"].resolve())


def test_recorder_journal_is_consumed_by_the_service(
    db: Session, settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    """Gravador (OBS em memória) → diário → serviço → ingestão: o formato de um serve ao outro."""
    import asyncio

    from cronista.recorder.core import Recorder
    from cronista.recorder.ports import STATE_STOPPED, RecordState
    from tests.test_recorder import FakeClock, FakeFeedback, MemoryLink, _started

    folder = tmp_path / "obs"
    folder.mkdir()
    shutil.copy(sorted(fixture_folders["normal"].iterdir())[0], folder / "OBS-2026.mp4")  # mtime = agora

    async def scenario() -> None:
        async def no_sleep(_: float) -> None:
            return None

        recorder = Recorder(MemoryLink(folder), FakeFeedback(), settings, clock=FakeClock(), sleep=no_sleep)
        await recorder.handle(_started(100.0))
        await recorder.press(MarkerKind.NOVO_DIA, FakeClock.at(100.5))
        await recorder.press(MarkerKind.MOMENTO, FakeClock.at(101.5))
        await recorder.handle(RecordState(STATE_STOPPED, str(folder / "OBS-2026.mp4"), FakeClock.at(103.0)))

    asyncio.run(scenario())
    (journal,) = folder.glob("*.markers.jsonl")
    settle(journal, folder)

    (result,) = scan(db, settings, folder)
    assert result.error is None
    (session,) = sessions(db)
    query = select(Marker).where(Marker.session_id == session.id).order_by(Marker.media_time_s)
    rows = list(db.scalars(query))
    assert [(r.kind, r.source, round(r.media_time_s, 1)) for r in rows] == [
        ("novo_dia", "journal", 0.5),
        ("momento", "journal", 1.5),
    ]
