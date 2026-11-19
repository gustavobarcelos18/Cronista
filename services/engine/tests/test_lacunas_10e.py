"""10E: lacunas de teste da auditoria (A14, B20) que não precisam de FFmpeg nem de mídia real."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from sqlalchemy.orm import Session

from cronista.audio.scream import ScreamHeuristic
from cronista.config import Settings
from cronista.db.models import MediaFile, Project, RecordingSession
from cronista.domain.models import MediaProbe
from cronista.ingest import stages as ingest_stages
from cronista.pipeline.stage import StageContext, StageError
from cronista.relevance.engine import Segment
from cronista.review import panel as panel_module
from cronista.review.panel import series_panel_full
from cronista.story.arc import allocate_time, build_chapters
from cronista.story.script import free_gaps

# ------------------------------------------------------------------ A14


def test_a14_ingest_rejects_a_recording_with_two_audio_tracks(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp_path: Path
) -> None:
    probe = MediaProbe(path="a.mp4", video_codec="h264", pix_fmt="yuv420p", fps="60/1", audio_streams=2)
    monkeypatch.setattr(ingest_stages, "probe_media", lambda *_: probe)
    ctx = StageContext(media_path=tmp_path / "a.mp4", out_dir=tmp_path, settings=settings, inputs={})
    with pytest.raises(StageError, match=r"2 faixa\(s\) de áudio; esperado 3"):
        ingest_stages.NormalizeStage().run(ctx)


def test_a14_empty_wav_gives_no_scream_events(tmp_path: Path) -> None:
    path = tmp_path / "vazio.wav"
    sf.write(str(path), np.zeros(0, dtype=np.float32), 16000)
    assert ScreamHeuristic().classify(path, pause=lambda: None) == []


# ------------------------------------------------------------------ B20


def test_b20_session_without_new_day_and_without_speech_is_one_chapter_with_one_free_gap() -> None:
    segs = [Segment(0, 100, "jogo", 0.6, ["r"], [], {}), Segment(100, 200, "jogo", 0.7, ["r"], [], {})]
    chapters = build_chapters([(1, segs)], {})
    assert [c.number for c in chapters] == [1]
    allocate_time(chapters, 600)
    assert sum(c.allocated_s for c in chapters) <= 200 + 1  # nunca passa do material
    assert free_gaps(0, 200, []) == [(0, 200)]


def test_b20_panel_with_two_projects_keeps_each_series_separate(
    monkeypatch: pytest.MonkeyPatch, db: Session
) -> None:
    for name, folder in (("serie-a", "fa"), ("serie-b", "fb")):
        project = Project(name=name, game="g")
        db.add(project)
        db.commit()
        session = RecordingSession(project_id=project.id, folder=folder)
        db.add(session)
        db.commit()
        db.add(MediaFile(session_id=session.id, path=f"{folder}.mp4"))
        db.commit()

    moments = {1: 1, 2: 3}  # a série A tem 1 momento mantido; a B tem 3

    def fake_effective(_db: Any, media_id: int) -> list[Segment]:
        return [Segment(n * 60, n * 60 + 30, "momento", 0.9, ["r"], [], {}) for n in range(moments[media_id])]

    monkeypatch.setattr(panel_module, "load_effective_segments", fake_effective)
    panel = series_panel_full(db)

    assert [p.projeto for p in panel.projetos] == ["serie-a", "serie-b"]
    a, b = panel.projetos
    assert 0 < a.total_min < b.total_min  # cada série soma só o próprio material
    assert all(len(p.sessoes) == 1 for p in panel.projetos)
    assert b.sessoes[0].acumulado_min == b.total_min  # o acumulado não vaza de uma série para a outra


# ------------------------------------------------------------------ B1 (10F)


def _two_sessions(db: Session) -> Project:
    project = Project(name="serie", game="g")
    db.add(project)
    db.commit()
    for n in (1, 2):
        session = RecordingSession(project_id=project.id, folder=f"f{n}")
        db.add(session)
        db.commit()
        db.add(MediaFile(session_id=session.id, path=f"{n}.mp4"))
        db.commit()
    return project


def test_b1_series_story_uses_one_target_and_one_chapter_across_sessions(
    monkeypatch: pytest.MonkeyPatch, db: Session
) -> None:
    from cronista.story import service

    project = _two_sessions(db)
    monkeypatch.setattr(
        service,
        "load_effective_segments",
        lambda _db, _media: [Segment(0, 600, "momento", 0.9, ["r"], [], {})],
    )
    series = service.build_series_story(db, project.id, 60)
    assert [c.number for c in series.chapters] == [1]  # sem `novo_dia`, o dia atravessa as duas sessões
    assert {i.span.file_id for c in series.chapters for i in c.items} == {1, 2}
    assert sum(c.allocated_s for c in series.chapters) <= 60 + 1

    per_session = [service.build_story(db, sid, 60) for sid in (1, 2)]
    assert sum(c.allocated_s for r in per_session for c in r.chapters) > 60  # o problema que a série resolve


def test_b1_series_story_rejects_unknown_project(db: Session) -> None:
    from cronista.story.service import StoryError, build_series_story

    with pytest.raises(StoryError, match="projeto 9 não existe"):
        build_series_story(db, 9)
