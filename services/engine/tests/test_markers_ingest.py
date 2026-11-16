"""Ingestão de marcadores sobre fixtures reais do FFmpeg (capítulos gravados com `-f ffmetadata`)."""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.config import Settings
from cronista.db.models import Marker, Project
from cronista.domain.models import MarkerKind
from cronista.ingest.ffmpeg import probe_chapters, run_ffmpeg
from cronista.ingest.journal import JournalWriter
from cronista.ingest.service import IngestReport, ingest_folder
from cronista.pipeline import AlwaysFreeGate
from tests.conftest import needs_ffmpeg

pytestmark = needs_ffmpeg


def _with_chapters(settings: Settings, src: Path, dst: Path, chapters: list[tuple[str, float]]) -> None:
    lines = [";FFMETADATA1"]
    for title, start in chapters:
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={int(start * 1000)}",
            f"END={int(start * 1000) + 500}",
        ]
        lines.append(f"title={title}")
    meta = dst.parent / "meta.txt"
    meta.write_text("\n".join(lines) + "\n", encoding="utf-8")
    run_ffmpeg(
        settings,
        ["-i", str(src), "-i", str(meta), "-map", "0", "-map_metadata", "1", "-c", "copy", str(dst)],
    )
    meta.unlink()


def _session_folder(tmp_path: Path, settings: Settings, base: Path, name: str) -> Path:
    folder = tmp_path / name
    folder.mkdir()
    shutil.copy(base, folder / "gravacao.mp4")
    return folder


def _markers(db: Session) -> list[Marker]:
    return list(db.scalars(select(Marker).order_by(Marker.media_frame)))


def _base(fixture_folders: dict[str, Path]) -> Path:
    return next(fixture_folders["normal"].iterdir())


def _ingest(db: Session, folder: Path, settings: Settings, project: str = "p") -> IngestReport:
    return ingest_folder(db, folder, settings, AlwaysFreeGate(), project)


def test_probe_chapters_reads_titles_and_times(
    settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    out = tmp_path / "c.mp4"
    _with_chapters(settings, _base(fixture_folders), out, [("momento|a1", 0.0), ("Chapter 2", 1.25)])
    # O muxer MP4 do FFmpeg força o 1º capítulo para 0 s (risco a conferir com o OBS real, 1C).
    chapters = probe_chapters(settings, out)
    assert [(c.title, c.media_frame) for c in chapters] == [("momento|a1", 0), ("Chapter 2", 75)]


def test_journal_and_file_agree_uses_file_time(
    db: Session, settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    folder = tmp_path / "s"
    folder.mkdir()
    _with_chapters(
        settings, _base(fixture_folders), folder / "gravacao.mp4",
        [("novo_dia|d1", 0.0), ("morte_falha|m1", 1.0)],
    )  # fmt: skip
    clock = iter([100.0, 100.0, 101.3])  # a fixture tem 2 s; m1 no diário cai em 1,3 s (arquivo diz 1,0)
    with JournalWriter(folder / "s.markers.jsonl", mono=lambda: next(clock)) as w:
        w.recording_started(str(folder / "gravacao.mp4"))
        w.marker(MarkerKind.NOVO_DIA, "d1")
        w.marker(MarkerKind.MORTE_FALHA, "m1")

    report = _ingest(db, folder, settings)
    assert report.ok
    rows = _markers(db)
    assert [(r.kind, r.marker_id, r.source) for r in rows] == [
        ("novo_dia", "d1", "file"),
        ("morte_falha", "m1", "file"),
    ]
    assert [r.media_frame for r in rows] == [0, 60]
    assert report.markers.warnings == []  # diário 1,3 s contra arquivo 1,0 s: diverge só 0,3 s (< 1 s)


def test_journal_only_when_file_has_no_chapters_and_reingest_is_idempotent(
    db: Session, settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    folder = _session_folder(tmp_path, settings, _base(fixture_folders), "s")
    clock = iter([10.0, 10.5, 11.5])
    with JournalWriter(folder / "s.markers.jsonl", mono=lambda: next(clock)) as w:
        w.recording_started("C:\\obs\\gravacao.mp4")  # caminho do ponto de vista do OBS: casa pelo nome
        w.marker(MarkerKind.NOVO_DIA, "d1")
        w.marker(MarkerKind.ENGRACADO, "e1")

    _ingest(db, folder, settings)
    first = [(r.kind, r.source, r.media_frame) for r in _markers(db)]
    assert first == [("novo_dia", "journal", 30), ("engracado", "journal", 90)]

    _ingest(db, folder, settings)
    assert len(_markers(db)) == 2  # reingerir não duplica


def test_divergence_and_file_only_marker_produce_warnings(
    db: Session, settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    folder = tmp_path / "s"
    folder.mkdir()
    _with_chapters(
        settings, _base(fixture_folders), folder / "gravacao.mp4",
        [("novo_dia|d1", 0.0), ("Chapter 3", 1.0), ("momento|m1", 1.9)],
    )  # fmt: skip
    clock = iter([0.0, 0.0, 0.4])  # m1 no diário: 0,4 s; no arquivo: 1,9 s → diverge
    with JournalWriter(folder / "s.markers.jsonl", mono=lambda: next(clock)) as w:
        w.recording_started("gravacao.mp4")
        w.marker(MarkerKind.NOVO_DIA, "d1")
        w.marker(MarkerKind.MOMENTO, "m1")

    report = _ingest(db, folder, settings)
    by_id = {r.marker_id: r for r in _markers(db)}
    assert by_id["m1"].media_frame == 114 and "divergem" in (by_id["m1"].warning or "")
    orphan = by_id["arquivo-1"]
    assert orphan.kind == "momento" and "só no arquivo" in (orphan.warning or "")
    assert len(report.markers.warnings) == 2


def test_open_construction_is_closed_at_session_end_with_warning(
    db: Session, settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    folder = _session_folder(tmp_path, settings, _base(fixture_folders), "s")
    clock = iter([0.0, 0.1, 0.5, 1.0])
    with JournalWriter(folder / "s.markers.jsonl", mono=lambda: next(clock)) as w:
        w.recording_started("gravacao.mp4")
        w.marker(MarkerKind.NOVO_DIA, "d1")
        w.marker(MarkerKind.CONSTRUCAO, "c1")  # ▶
        w.marker(MarkerKind.CONSTRUCAO, "c2")  # ■
    # mais um ▶ sem ■
    clock2 = iter([1.5])
    with JournalWriter(folder / "s.markers.jsonl", mono=lambda: next(clock2)) as w:
        w.marker(MarkerKind.CONSTRUCAO, "c3")

    report = _ingest(db, folder, settings)
    phases = [(r.marker_id, r.phase, r.source) for r in _markers(db) if r.kind == "construcao"]
    assert phases == [
        ("c1", "start", "journal"),
        ("c2", "end", "journal"),
        ("c3", "start", "journal"),
        ("c3-fim", "end", "synthetic"),
    ]
    assert any("construção aberta" in w for w in report.markers.warnings)


def test_implicit_day_only_on_first_session_without_novo_dia(
    db: Session, settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    base = _base(fixture_folders)
    first = _session_folder(tmp_path, settings, base, "s1")
    _ingest(db, first, settings)
    days = [r for r in _markers(db) if r.kind == "novo_dia"]
    assert len(days) == 1 and days[0].source == "synthetic" and days[0].media_frame == 0

    second = _session_folder(tmp_path, settings, base, "s2")  # continua o dia anterior
    (second / "gravacao.mp4").write_bytes((second / "gravacao.mp4").read_bytes() + b"\0")  # hash diferente
    _ingest(db, second, settings)
    assert len([r for r in _markers(db) if r.kind == "novo_dia"]) == 1

    project = db.scalar(select(Project).where(Project.name == "p"))
    assert project is not None and len(project.sessions) == 2
