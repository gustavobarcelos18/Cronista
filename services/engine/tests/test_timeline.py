"""Reconstrução do tempo de mídia e reconciliação (código puro, sem FFmpeg)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cronista.domain.journal import (
    FileChanged,
    JournalEvent,
    MarkerPressed,
    Paused,
    RecordingStarted,
    RecordingStopped,
    Unpaused,
    chapter_title,
    parse_chapter_title,
)
from cronista.domain.models import MarkerKind
from cronista.domain.timeline import (
    FileChapter,
    JournalMarker,
    MarkerSource,
    drop_obs_bookends,
    reconcile_file,
    reconstruct_media_times,
)

UTC_NOW = datetime(2026, 11, 16, tzinfo=UTC)


def start(t: float, path: str = "a.mp4") -> JournalEvent:
    return RecordingStarted(mono_s=t, utc=UTC_NOW, path=path)


def mark(t: float, marker_id: str, kind: MarkerKind = MarkerKind.MOMENTO) -> JournalEvent:
    return MarkerPressed(mono_s=t, utc=UTC_NOW, kind=kind, marker_id=marker_id)


def test_simple_recording_uses_time_since_start() -> None:
    result = reconstruct_media_times(
        [start(1000.0), mark(1012.5, "m1"), RecordingStopped(mono_s=1100, utc=UTC_NOW)]
    )
    (marker,) = result.markers
    assert marker.media_time_s == pytest.approx(12.5, abs=0.1) and marker.file_name == "a.mp4"
    assert result.warnings == []


def test_pauses_are_discounted() -> None:
    events: list[JournalEvent] = [
        start(100.0),
        Paused(mono_s=110, utc=UTC_NOW),
        Unpaused(mono_s=140, utc=UTC_NOW),  # 30 s de pausa
        mark(150.0, "m1"),
        Paused(mono_s=160, utc=UTC_NOW),
        Unpaused(mono_s=165, utc=UTC_NOW),  # +5 s
        mark(170.0, "m2"),
    ]
    times = [m.media_time_s for m in reconstruct_media_times(events).markers]
    assert times == pytest.approx([20.0, 35.0], abs=0.1)  # 150-100-30 e 170-100-35


def test_file_split_restarts_the_clock_in_the_new_file() -> None:
    events: list[JournalEvent] = [
        start(0.0, "a.mp4"),
        mark(50.0, "m1"),
        FileChanged(mono_s=100.0, utc=UTC_NOW, path="b.mp4"),
        mark(130.0, "m2"),
    ]
    first, second = reconstruct_media_times(events).markers
    assert first.file_name == "a.mp4" and first.media_time_s == pytest.approx(50.0, abs=0.1)
    assert second.file_name == "b.mp4" and second.media_time_s == pytest.approx(30.0, abs=0.1)


def test_pause_across_file_split_keeps_counting_in_new_file() -> None:
    events: list[JournalEvent] = [
        start(0.0, "a.mp4"),
        Paused(mono_s=90, utc=UTC_NOW),
        FileChanged(mono_s=100.0, utc=UTC_NOW, path="b.mp4"),
        Unpaused(mono_s=110, utc=UTC_NOW),
        mark(130.0, "m1"),
    ]
    (marker,) = reconstruct_media_times(events).markers
    assert marker.media_time_s == pytest.approx(20.0, abs=0.1)  # 130 - 100 - 10 s de pausa


def test_crash_without_recording_stopped_still_resolves() -> None:
    result = reconstruct_media_times([start(0.0), mark(20.0, "m1"), mark(40.0, "m2")])  # sem stopped
    assert [m.media_time_s for m in result.markers] == pytest.approx([20.0, 40.0], abs=0.1)


def test_marker_outside_recording_is_ignored_with_warning() -> None:
    events: list[JournalEvent] = [
        mark(5.0, "antes"),
        start(10.0),
        RecordingStopped(mono_s=20, utc=UTC_NOW),
        mark(25.0, "depois"),
    ]
    result = reconstruct_media_times(events)
    assert result.markers == []
    assert len(result.warnings) == 2 and "fora de gravação" in result.warnings[0]


def test_marker_during_pause_lands_at_the_pause_point_with_warning() -> None:
    result = reconstruct_media_times([start(0.0), Paused(mono_s=30, utc=UTC_NOW), mark(50.0, "m1")])
    (marker,) = result.markers
    assert marker.media_time_s == pytest.approx(30.0, abs=0.1) and result.warnings


def jm(marker_id: str, t: float, kind: MarkerKind = MarkerKind.MOMENTO) -> JournalMarker:
    return JournalMarker(marker_id, kind, "a.mp4", t)


def test_reconcile_agreeing_prefers_file_time_without_warning() -> None:
    (r,) = reconcile_file("a.mp4", [jm("x", 10.0)], [FileChapter("momento|x", 10.4)])
    assert (r.source, r.media_time_s, r.warning) == (MarkerSource.FILE, 10.4, None)


def test_reconcile_journal_only_uses_reconstructed_time() -> None:
    (r,) = reconcile_file("a.mp4", [jm("x", 10.0, MarkerKind.NOVO_DIA)], [])
    assert (r.source, r.media_time_s, r.kind, r.warning) == (
        MarkerSource.JOURNAL,
        10.0,
        MarkerKind.NOVO_DIA,
        None,
    )


def test_reconcile_divergence_uses_file_and_warns() -> None:
    (r,) = reconcile_file("a.mp4", [jm("x", 10.0)], [FileChapter("momento|x", 25.0)])
    assert r.source is MarkerSource.FILE and r.media_time_s == 25.0
    assert r.warning is not None and "divergem" in r.warning


def test_reconcile_file_only_becomes_momento_with_warning() -> None:
    resolved = reconcile_file("a.mp4", [], [FileChapter("morte_falha|y", 5.0), FileChapter("Chapter 1", 8.0)])
    assert [(r.kind, r.media_time_s) for r in resolved] == [
        (MarkerKind.MOMENTO, 5.0),
        (MarkerKind.MOMENTO, 8.0),
    ]
    assert all(r.warning and "Momento" in r.warning for r in resolved)
    assert len({r.marker_id for r in resolved}) == 2


def test_chapter_title_round_trip() -> None:
    assert parse_chapter_title(chapter_title(MarkerKind.NOVO_DIA, "abc")) == (MarkerKind.NOVO_DIA, "abc")
    for bad in ("Chapter 1", "inexistente|x", "momento|", ""):
        assert parse_chapter_title(bad) is None


def test_real_obs_chapters_ignore_start_and_dummy_bookends() -> None:
    """Saída real de `ffprobe -show_chapters` de uma gravação do OBS (2 toques da hotkey nativa)."""
    chapters = [
        FileChapter("Iniciar", 0.0),
        FileChapter("Sem nome 1", 403.233),
        FileChapter("Sem nome 2", 421.733),
        FileChapter("Dummy", 425.301),
    ]
    resolved = reconcile_file("testeia.mp4", [], chapters)
    assert [(r.kind, r.media_time_s) for r in resolved] == [
        (MarkerKind.MOMENTO, 403.233),
        (MarkerKind.MOMENTO, 421.733),
    ]


def test_recording_without_any_marker_has_no_markers() -> None:
    assert reconcile_file("a.mp4", [], [FileChapter("Iniciar", 0.0), FileChapter("Dummy", 60.0)]) == []


def test_drop_obs_bookends_keeps_a_typed_marker_at_zero_and_real_last_chapters() -> None:
    kept = drop_obs_bookends([FileChapter("novo_dia|d1", 0.0), FileChapter("Sem nome 1", 30.0)])
    assert [c.title for c in kept] == ["novo_dia|d1", "Sem nome 1"]
