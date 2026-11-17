"""Relatório HTML da sessão e comandos `analyze`/`report`."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from cronista import cli
from cronista.audio.ports import AudioModels, SoundEventSpan
from cronista.audio.report import (
    MAX_POINTS,
    downsample,
    fmt_time,
    render_session_report,
    write_session_report,
)
from cronista.audio.service import analyze_session
from cronista.config import Settings
from cronista.db.models import Marker, MediaFile, RecordingSession
from cronista.ingest.service import ingest_folder
from cronista.pipeline import AlwaysFreeGate
from tests.conftest import needs_ffmpeg
from tests.fakes_audio import FakeClassifier, FakeDetector, FakeTranscriber


def test_fmt_time_uses_the_60fps_grid() -> None:
    assert fmt_time(0) == "0:00" and fmt_time(60 * 75) == "1:15" and fmt_time(60 * 3725) == "1:02:05"


def test_downsample_keeps_peaks_and_reports_the_group() -> None:
    values = np.zeros(10_000, dtype=np.float32)
    values[4321] = 9.0
    reduced, group = downsample(values)
    assert len(reduced) <= MAX_POINTS and group == 9 and reduced.max() == 9.0
    small, one = downsample(values[:100])
    assert one == 1 and len(small) == 100


@pytest.fixture
def analyzed(db: Session, settings: Settings, fixture_folders: dict[str, Path]) -> int:
    assert ingest_folder(db, fixture_folders["normal"], settings, AlwaysFreeGate()).ok
    session_id = db.scalars(select(RecordingSession.id)).one()
    media = db.scalars(select(MediaFile)).one()
    db.add(
        Marker(session_id=session_id, media_file_id=media.id, marker_id="m1", kind="momento", media_frame=60)
    )
    db.commit()
    models = AudioModels(
        FakeDetector([(0.2, 1.5)]),
        FakeTranscriber("<script>alert(1)</script> oi"),
        FakeClassifier([SoundEventSpan(label="risada", start_s=0.5, end_s=1.0, score=0.9)]),
    )
    assert analyze_session(db, session_id, settings, AlwaysFreeGate(), models).ok
    return session_id


@needs_ffmpeg
def test_report_has_charts_events_speech_and_markers_and_escapes_text(db: Session, analyzed: int) -> None:
    page = render_session_report(db, analyzed)
    assert page.startswith("<!doctype html>") and "<polyline" in page
    for title in ("Jogo: novidade", "Jogo: periodicidade", "Microfone: energia"):
        assert title in page
    assert "momento em 0:01" in page  # marcador sobreposto aos gráficos
    assert "risada" in page and "Fala transcrita" in page
    assert "<script>" not in page and "&lt;script&gt;" in page  # transcrição nunca vira HTML
    assert "http://" not in page and "https://" not in page  # abre sem rede
    assert "prefers-color-scheme:dark" in page


@needs_ffmpeg
def test_report_before_analysis_says_how_to_get_signals(
    db: Session, settings: Settings, fixture_folders: dict[str, Path]
) -> None:
    ingest_folder(db, fixture_folders["normal"], settings, AlwaysFreeGate())
    session_id = db.scalars(select(RecordingSession.id)).one()
    assert "cronista analyze" in render_session_report(db, session_id)


def test_report_for_an_unknown_session_is_a_lookup_error(db: Session) -> None:
    with pytest.raises(LookupError, match="Sessão 7"):
        render_session_report(db, 7)


@needs_ffmpeg
def test_write_report_creates_the_file(
    db: Session, settings: Settings, analyzed: int, tmp_path: Path
) -> None:
    path = write_session_report(db, analyzed, settings)
    assert path == settings.data_dir / "reports" / f"sessao-{analyzed}.html" and path.stat().st_size > 1000
    custom = write_session_report(db, analyzed, settings, tmp_path / "x" / "r.html")
    assert custom.is_file()


@needs_ffmpeg
def test_cli_analyze_and_report(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, fixture_folders: dict[str, Path], tmp_path: Path
) -> None:
    from cronista.db.session import open_db

    with open_db(settings.db_path) as db:
        assert ingest_folder(db, fixture_folders["normal"], settings, AlwaysFreeGate()).ok
        session_id = db.scalars(select(RecordingSession.id)).one()
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    runner = CliRunner()

    result = runner.invoke(cli.app, ["analyze", str(session_id)])
    assert result.exit_code == 0, result.output
    assert "audio_signals" in result.output and "não rodou: fala" in result.output

    out = tmp_path / "r.html"
    result = runner.invoke(cli.app, ["report", str(session_id), "--out", str(out)])
    assert result.exit_code == 0 and out.is_file()

    assert runner.invoke(cli.app, ["analyze", "99"]).exit_code == 1
    assert runner.invoke(cli.app, ["report", "99"]).exit_code == 1
    status = runner.invoke(cli.app, ["status"])
    assert "audio_signals: done" in status.output


def test_report_keeps_each_producer_apart(db: Session, tmp_path: Path) -> None:
    """Dois transcritores no benchmark: uma tabela de fala por modelo e faixas separadas, nunca misturadas."""
    from cronista.audio.events import replace_events
    from cronista.db.models import Project
    from tests.test_events import make_event

    project = Project(name="p")
    db.add(project)
    db.flush()
    session = RecordingSession(project_id=project.id, folder="x")
    db.add(session)
    db.flush()
    media = MediaFile(session_id=session.id, path=str(tmp_path / "a.mp4"))
    db.add(media)
    db.commit()
    replace_events(db, media.id, "speech", "vad-asr-a", [make_event("fala", 60, 120, quote="texto A")])
    replace_events(db, media.id, "speech", "vad-asr-b", [make_event("fala", 60, 120, quote="texto B")])
    replace_events(db, media.id, "sound_events", "mic-sed", [make_event("risada", 200, 260)])

    page = render_session_report(db, session.id)
    assert page.count("<h3>Fala transcrita") == 2
    assert "Fala transcrita (speech:vad-asr-a)" in page and "Fala transcrita (speech:vad-asr-b)" in page
    assert "fala (speech:vad-asr-a)" in page and "fala (speech:vad-asr-b)" in page  # faixas separadas
    assert ">risada<" in page  # tipo com um produtor só mantém o nome simples


@needs_ffmpeg
def test_report_has_video_section_with_thumbnails_when_settings_are_given(
    db: Session, settings: Settings, analyzed: int
) -> None:
    page = render_session_report(db, analyzed, settings)
    assert "<h2>Vídeo</h2>" in page and "Vídeo: movimento entre quadros" in page
    assert "Estados de tela" in page
    # os eventos de vídeo não aparecem misturados nas faixas de áudio
    assert page.count("<h3>Eventos</h3>") == 1


@needs_ffmpeg
def test_only_limits_the_analysis_and_rejects_unknown_values(
    db: Session, settings: Settings, fixture_folders: dict[str, Path]
) -> None:
    from cronista.audio.service import AnalysisError

    assert ingest_folder(db, fixture_folders["normal"], settings, AlwaysFreeGate()).ok
    session_id = db.scalars(select(RecordingSession.id)).one()
    only_video = analyze_session(db, session_id, settings, AlwaysFreeGate(), None, "video")
    executed = next(iter(only_video.files.values())).executed
    assert set(executed) == {"video_signals", "video_scenes", "video_hud"} and not only_video.skipped
    only_audio = analyze_session(db, session_id, settings, AlwaysFreeGate(), None, "audio")
    assert "video_signals" not in next(iter(only_audio.files.values())).executed
    with pytest.raises(AnalysisError, match="--only"):
        analyze_session(db, session_id, settings, AlwaysFreeGate(), None, "tudo")
