"""Reconstrução do tempo de mídia e reconciliação (código puro, sem FFmpeg)."""

from __future__ import annotations

from datetime import UTC, datetime

from cronista.domain.frames import FPS, frame_to_seconds, seconds_to_frame
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
    assert marker.media_frame == 750 and marker.file_name == "a.mp4"
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
    frames = [m.media_frame for m in reconstruct_media_times(events).markers]
    assert frames == [1200, 2100]  # 150-100-30 e 170-100-35 s


def test_file_split_restarts_the_clock_in_the_new_file() -> None:
    events: list[JournalEvent] = [
        start(0.0, "a.mp4"),
        mark(50.0, "m1"),
        FileChanged(mono_s=100.0, utc=UTC_NOW, path="b.mp4"),
        mark(130.0, "m2"),
    ]
    first, second = reconstruct_media_times(events).markers
    assert first.file_name == "a.mp4" and first.media_frame == 3000
    assert second.file_name == "b.mp4" and second.media_frame == 1800


def test_pause_across_file_split_keeps_counting_in_new_file() -> None:
    events: list[JournalEvent] = [
        start(0.0, "a.mp4"),
        Paused(mono_s=90, utc=UTC_NOW),
        FileChanged(mono_s=100.0, utc=UTC_NOW, path="b.mp4"),
        Unpaused(mono_s=110, utc=UTC_NOW),
        mark(130.0, "m1"),
    ]
    (marker,) = reconstruct_media_times(events).markers
    assert marker.media_frame == 1200  # 130 - 100 - 10 s de pausa


def test_crash_without_recording_stopped_still_resolves() -> None:
    result = reconstruct_media_times([start(0.0), mark(20.0, "m1"), mark(40.0, "m2")])  # sem stopped
    assert [m.media_frame for m in result.markers] == [1200, 2400]


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
    assert marker.media_frame == 1800 and result.warnings


def jm(marker_id: str, frame: int, kind: MarkerKind = MarkerKind.MOMENTO) -> JournalMarker:
    return JournalMarker(marker_id, kind, "a.mp4", frame)


def test_reconcile_agreeing_prefers_file_time_without_warning() -> None:
    (r,) = reconcile_file("a.mp4", [jm("x", 600)], [FileChapter("momento|x", 624)])  # 10,0 s e 10,4 s
    assert (r.source, r.media_frame, r.warning) == (MarkerSource.FILE, 624, None)


def test_reconcile_journal_only_uses_reconstructed_time() -> None:
    (r,) = reconcile_file("a.mp4", [jm("x", 600, MarkerKind.NOVO_DIA)], [])
    assert (r.source, r.media_frame, r.kind, r.warning) == (
        MarkerSource.JOURNAL,
        600,
        MarkerKind.NOVO_DIA,
        None,
    )


def test_reconcile_divergence_uses_file_and_warns() -> None:
    (r,) = reconcile_file("a.mp4", [jm("x", 600)], [FileChapter("momento|x", 1500)])
    assert r.source is MarkerSource.FILE and r.media_frame == 1500
    assert r.warning is not None and "divergem" in r.warning


def test_reconcile_file_only_becomes_momento_with_warning() -> None:
    resolved = reconcile_file("a.mp4", [], [FileChapter("morte_falha|y", 300), FileChapter("Chapter 1", 480)])
    assert [(r.kind, r.media_frame) for r in resolved] == [
        (MarkerKind.MOMENTO, 300),
        (MarkerKind.MOMENTO, 480),
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
        FileChapter("Iniciar", 0),
        FileChapter("Sem nome 1", seconds_to_frame(403.233)),
        FileChapter("Sem nome 2", seconds_to_frame(421.733)),
        FileChapter("Dummy", seconds_to_frame(425.301)),
    ]
    resolved = reconcile_file("testeia.mp4", [], chapters)
    assert [(r.kind, r.media_frame) for r in resolved] == [
        (MarkerKind.MOMENTO, 24194),
        (MarkerKind.MOMENTO, 25304),
    ]


def test_recording_without_any_marker_has_no_markers() -> None:
    assert reconcile_file("a.mp4", [], [FileChapter("Iniciar", 0), FileChapter("Dummy", 3600)]) == []


def test_drop_obs_bookends_keeps_a_typed_marker_at_zero_and_real_last_chapters() -> None:
    kept = drop_obs_bookends([FileChapter("novo_dia|d1", 0), FileChapter("Sem nome 1", 1800)])
    assert [c.title for c in kept] == ["novo_dia|d1", "Sem nome 1"]


def test_seconds_round_to_the_nearest_frame_never_negative() -> None:
    assert FPS == 60
    assert seconds_to_frame(12.5) == 750
    assert seconds_to_frame(12.508) == 750  # 750,48 quadros
    assert seconds_to_frame(12.51) == 751  # 750,6 quadros
    assert seconds_to_frame(-0.2) == 0
    assert frame_to_seconds(90) == 1.5
    assert all(seconds_to_frame(frame_to_seconds(f)) == f for f in (0, 1, 59, 60, 24194, 2_160_000))


def test_reconstructed_time_lands_on_the_right_frame_with_fractional_clock() -> None:
    """Toque com relógio fracionado (sem arredondar para baixo): 1012,508 - 1000 = 12,508 s → quadro 750."""
    events: list[JournalEvent] = [start(1000.0), mark(1012.508, "a"), mark(1012.51, "b")]
    assert [m.media_frame for m in reconstruct_media_times(events).markers] == [750, 751]
