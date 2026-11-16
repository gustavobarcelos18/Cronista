"""Escrita e leitura do diário `.markers.jsonl`."""

from __future__ import annotations

from pathlib import Path

from cronista.domain.journal import MarkerPressed
from cronista.domain.models import MarkerKind
from cronista.domain.timeline import reconstruct_media_times
from cronista.ingest.journal import JournalWriter, find_journals, read_journal


def test_writer_round_trips_all_event_types(tmp_path: Path) -> None:
    path = tmp_path / "s.markers.jsonl"
    clock = iter(float(i) for i in range(100))
    with JournalWriter(path, mono=lambda: next(clock)) as w:
        w.recording_started("a.mp4")
        w.marker(MarkerKind.NOVO_DIA, "d1")
        w.paused()
        w.unpaused()
        w.file_changed("b.mp4")
        w.marker(MarkerKind.CONSTRUCAO, "c1")
        w.recording_stopped()
    events, warnings = read_journal(path)
    assert warnings == []
    assert [e.type for e in events] == [
        "recording_started", "marker", "paused", "unpaused", "file_changed", "marker", "recording_stopped",
    ]  # fmt: skip
    assert find_journals(tmp_path) == [path]


def test_lines_are_on_disk_immediately_after_each_write(tmp_path: Path) -> None:
    path = tmp_path / "s.markers.jsonl"
    writer = JournalWriter(path)
    writer.recording_started("a.mp4")
    writer.marker(MarkerKind.MOMENTO, "m1")
    # sem close(): se o programa morrer agora, as duas linhas já estão no arquivo
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    writer.close()


def test_reopening_after_a_truncated_last_line_does_not_corrupt_the_journal(tmp_path: Path) -> None:
    path = tmp_path / "s.markers.jsonl"
    with JournalWriter(path) as w:
        w.recording_started("a.mp4")
        w.marker(MarkerKind.MOMENTO, "m1")
    data = path.read_bytes()
    path.write_bytes(data[:-15])  # queda no meio da última linha (sem `\n`)

    with JournalWriter(path) as w:  # reabre
        w.marker(MarkerKind.MORTE_FALHA, "m2")

    events, warnings = read_journal(path)
    assert len(warnings) == 1  # só a linha cortada se perdeu
    markers = [e for e in events if isinstance(e, MarkerPressed)]
    assert [m.marker_id for m in markers] == ["m2"]
    assert reconstruct_media_times(events).markers  # o resto continua utilizável


def test_garbage_lines_are_skipped_with_warning(tmp_path: Path) -> None:
    path = tmp_path / "s.markers.jsonl"
    with JournalWriter(path) as w:
        w.recording_started("a.mp4")
    with path.open("a", encoding="utf-8") as f:
        f.write("isto não é json\n\n")
    events, warnings = read_journal(path)
    assert len(events) == 1 and len(warnings) == 1
