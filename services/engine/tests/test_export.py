"""Exportação para o Resolve: timeline OTIO, FCPXML e a validação estrutural."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import opentimelineio as otio
import pytest
from sqlalchemy.orm import Session

from cronista.config import Settings
from cronista.db.models import MediaFile
from cronista.export.fcpxml import check_fcpxml, render_fcpxml
from cronista.export.service import export_session
from cronista.export.timeline import build_timeline
from cronista.ingest.service import ingest_folder
from cronista.montage import SessionPlanError, plan_session
from cronista.pipeline import AlwaysFreeGate
from tests.conftest import needs_ffmpeg
from tests.test_preview import _put_markers

pytestmark = needs_ffmpeg


@pytest.fixture
def short_window(settings: Settings) -> Settings:
    """Janela curta (0,5 s antes, 0,25 s depois) para os trechos ficarem diferentes entre si."""
    return settings.model_copy(update={"preview_pre_s": 0.5, "preview_post_s": 0.25})


def _split_session(db: Session, settings: Settings, fixture_folders: dict[str, Path]) -> int:
    report = ingest_folder(db, fixture_folders["split"], settings, AlwaysFreeGate(), "p")
    assert report.ok
    files = db.query(MediaFile).order_by(MediaFile.ordinal).all()
    _put_markers(
        db, report.session_id, [(files[0].id, "a", 60), (files[1].id, "b", 30), (files[1].id, "c", 90)]
    )
    return report.session_id


def test_timeline_has_one_clip_per_marker_on_three_tracks_in_whole_frames(
    db: Session, short_window: Settings, fixture_folders: dict[str, Path]
) -> None:
    session_id = _split_session(db, short_window, fixture_folders)
    timeline = build_timeline(plan_session(db, session_id, short_window), "t")

    names = [t.name for t in timeline.tracks]
    assert names == ["V1", "A1", "A2"]
    for track in timeline.tracks:
        assert len(track) == 3
    ranges = [(c.source_range.start_time.value, c.source_range.duration.value) for c in timeline.tracks[0]]
    assert ranges == [(30, 45), (0, 45), (60, 45)]
    for track in timeline.tracks:
        for clip in track:
            assert clip.source_range.start_time.rate == 60
            assert clip.source_range.duration.value == int(clip.source_range.duration.value)
    assert timeline.duration().to_seconds() == pytest.approx(135 / 60)


def test_audio_tracks_use_the_extracted_wavs_and_video_the_master(
    db: Session, short_window: Settings, fixture_folders: dict[str, Path]
) -> None:
    session_id = _split_session(db, short_window, fixture_folders)
    timeline = build_timeline(plan_session(db, session_id, short_window), "t")
    urls = [t[0].media_reference.target_url for t in timeline.tracks]
    assert urls[0].endswith(".mp4")
    assert urls[1].endswith("game.wav")
    assert urls[2].endswith("mic.wav")


def test_export_writes_valid_fcpxml_and_otio_that_roundtrips(
    db: Session, short_window: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    session_id = _split_session(db, short_window, fixture_folders)
    report = export_session(db, session_id, short_window, tmp_path / "out")

    assert report.problems == []
    assert report.clips == 3 and report.duration_s == pytest.approx(135 / 60)
    xml = report.fcpxml_path.read_text(encoding="utf-8")
    root = ET.fromstring(xml)
    assert root.find("resources/format").get("frameDuration") == "1/60s"  # type: ignore[union-attr]
    assert root.find("resources/format").get("width") == "1920"  # type: ignore[union-attr]
    assert root.findall("asset-clip") == []
    # Dois masters + um WAV de jogo e um de microfone por master = 6 assets.
    assert len(root.findall("resources/asset")) == 6

    loaded = otio.adapters.read_from_file(str(report.otio_path))
    assert isinstance(loaded, otio.schema.Timeline)
    assert [len(t) for t in loaded.tracks] == [3, 3, 3]


def test_export_requires_audio_wavs(
    db: Session, short_window: Settings, fixture_folders: dict[str, Path]
) -> None:
    session_id = _split_session(db, short_window, fixture_folders)
    for wav in short_window.cache_dir.rglob("*.wav"):
        wav.unlink()
    with pytest.raises(SessionPlanError, match="WAVs"):
        build_timeline(plan_session(db, session_id, short_window), "t")


def test_export_errors_are_clear(db: Session, settings: Settings) -> None:
    with pytest.raises(SessionPlanError, match="não existe"):
        export_session(db, 99, settings)


# --- validação estrutural (puro, sem FFmpeg) ---

GOOD = """<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.8">
  <resources>
    <format id="r1" frameDuration="1/60s"/>
    <asset id="r2" format="r1" duration="2/1s" start="0s"/>
  </resources>
  <project name="p">
    <sequence duration="2/1s" format="r1">
      <spine>
        <clip name="c" offset="0s" duration="2/1s" start="1/2s">
          <video ref="r2" offset="0s" duration="2/1s"/>
          <clip lane="-1" offset="0s" duration="2/1s"/>
          <clip lane="-2" offset="0s" duration="2/1s"/>
        </clip>
      </spine>
    </sequence>
  </project>
</fcpxml>
"""


def test_check_accepts_a_good_document() -> None:
    assert check_fcpxml(GOOD) == []


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ('frameDuration="1/60s"', 'frameDuration="1001/60000s"', "60 fps exatos"),
        ('<video ref="r2"', '<video ref="r9"', "ref 'r9'"),
        ('start="1/2s"', 'start="1/7s"', "fora da grade"),
        ('sequence duration="2/1s"', 'sequence duration="3/1s"', "duração da sequência"),
        ('<clip lane="-2" offset="0s" duration="2/1s"/>', "", "lanes de áudio"),
        ("<project", '<asset-clip name="x" ref="r2" format="r1"/><project', "solto na raiz"),
        ('offset="0s" duration="2/1s" start', 'offset="zero" duration="2/1s" start', "não é um tempo"),
    ],
)
def test_check_flags_each_defect(old: str, new: str, expected: str) -> None:
    assert GOOD.count(old) >= 1
    problems = check_fcpxml(GOOD.replace(old, new, 1))
    assert any(expected in p for p in problems), problems


def test_check_reports_malformed_xml() -> None:
    assert "mal formado" in check_fcpxml("<fcpxml><resources></fcpxml>")[0]


def test_render_strips_loose_asset_clips_from_adapter_output() -> None:
    timeline = otio.schema.Timeline(name="t")
    track = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    reference = otio.schema.ExternalReference(
        target_url="file:///x/m.mp4",
        available_range=otio.opentime.TimeRange(
            otio.opentime.RationalTime(0, 60), otio.opentime.RationalTime(600, 60)
        ),
    )
    track.append(
        otio.schema.Clip(
            name="c",
            media_reference=reference,
            source_range=otio.opentime.TimeRange(
                otio.opentime.RationalTime(60, 60), otio.opentime.RationalTime(120, 60)
            ),
        )
    )
    timeline.tracks.append(track)
    xml = render_fcpxml(timeline)
    assert "<asset-clip" not in xml
    assert 'uid=""' not in xml
