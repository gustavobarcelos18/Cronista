"""Etapas de fala e eventos sonoros com modelos falsos: quadros, filtros do microfone, variantes e serviço."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cronista.audio.events import events_from_result, load_events
from cronista.audio.ports import AudioModels, SoundEventSpan, SpeechSpan, Utterance
from cronista.audio.service import AnalysisError, analyze_session
from cronista.audio.stages import SoundEventsStage, SpeechStage, analysis_stages
from cronista.config import Settings
from cronista.db.models import Artifact, Event, MediaFile, RecordingSession
from cronista.domain.models import StageResult
from cronista.pipeline import AlwaysFreeGate, StageContext, StageError
from tests.conftest import needs_ffmpeg
from tests.fakes_audio import FakeClassifier, FakeDetector, FakeTranscriber


@pytest.fixture
def ctx(settings: Settings, tmp_path: Path) -> StageContext:
    for name in ("game", "mic"):
        sf.write(str(tmp_path / f"{name}.wav"), np.zeros(48000, dtype=np.float32), 48000)
    return StageContext(
        media_path=tmp_path / "m.mp4",
        out_dir=tmp_path,
        settings=settings,
        inputs={
            "audio": StageResult(data={"game": str(tmp_path / "game.wav"), "mic": str(tmp_path / "mic.wav")})
        },
    )


def test_speech_becomes_events_in_frames_with_provenance(ctx: StageContext) -> None:
    stage = SpeechStage(FakeDetector([(1.0, 2.5)]), FakeTranscriber("oi pessoal"))
    result = stage.run(ctx)
    (event,) = events_from_result(result) or []
    assert event.kind == "fala" and event.evidence.quote == "oi pessoal"
    assert (event.evidence.start_frame, event.evidence.end_frame) == (60, 150)  # 1,0 s e 2,5 s a 60 fps
    assert event.evidence.model == "fake-asr" and event.evidence.confidence == 0.9
    assert event.payload["words"][0] == {
        "text": "oi",
        "start_frame": 60,
        "end_frame": 105,
        "probability": 1.0,
    }
    assert event.payload["vad"] == ["fake-vad", "1"]
    assert stage.variant == "fake-vad-fake-asr"


def test_empty_transcription_gives_no_event_and_a_warning(ctx: StageContext) -> None:
    result = SpeechStage(FakeDetector([]), FakeTranscriber()).run(ctx)
    assert events_from_result(result) == []
    assert any("Nenhuma fala" in w for w in result.warnings)
    blank = SpeechStage(FakeDetector([(0.0, 1.0)]), FakeTranscriber("   ")).run(ctx)
    assert events_from_result(blank) == []


def test_inverted_interval_from_an_adapter_is_a_stage_error(ctx: StageContext) -> None:
    class Broken(FakeDetector):
        def detect(self, wav: Path, *, pause: object) -> list[SpeechSpan]:
            return [SpeechSpan.model_construct(start_s=5.0, end_s=2.0)]

    with pytest.raises(StageError, match="invertido"):
        SpeechStage(Broken(), FakeTranscriber()).run(ctx)


def test_mic_keeps_only_laughter_and_shouts_and_drops_low_scores(ctx: StageContext) -> None:
    found = [
        SoundEventSpan(label="risada", start_s=1.0, end_s=2.0, score=0.8),
        SoundEventSpan(label="grito", start_s=3.0, end_s=3.5, score=0.2),  # abaixo do corte
        SoundEventSpan(label="teclado", start_s=4.0, end_s=4.1, score=0.9),  # descartado no microfone
        SoundEventSpan(label="respiracao", start_s=5.0, end_s=5.5, score=0.9),
    ]
    stage = SoundEventsStage(FakeClassifier(found), "mic")
    result = stage.run(ctx)
    assert [e.kind for e in events_from_result(result) or []] == ["risada"]
    assert result.data["dropped"] == 3
    # No jogo todo rótulo acima do corte vale.
    game = SoundEventsStage(FakeClassifier(found), "game").run(ctx)
    assert sorted(e.kind for e in events_from_result(game) or []) == ["respiracao", "risada", "teclado"]


def test_sound_events_reject_unknown_track() -> None:
    with pytest.raises(ValueError, match="faixa desconhecida"):
        SoundEventsStage(FakeClassifier(), "mix")  # o mix nunca é analisado


def test_threshold_and_models_are_part_of_the_cache_key(settings: Settings) -> None:
    a = SoundEventsStage(FakeClassifier(), "game", 0.3).params(settings)
    assert a != SoundEventsStage(FakeClassifier(), "game", 0.5).params(settings)
    assert a != SoundEventsStage(FakeClassifier(), "mic", 0.3).params(settings)


def test_analysis_stages_depend_on_the_available_models() -> None:
    # dev: só CPU (sinais + detector de grito por energia, que não usa modelo)
    assert [s.name for s in analysis_stages(AudioModels())] == ["audio_signals", "sound_events"]
    full = AudioModels(FakeDetector(), FakeTranscriber(), FakeClassifier())
    assert [s.name for s in analysis_stages(full)] == [
        "audio_signals",
        "speech",
        "sound_events",
        "sound_events",
        "sound_events",
    ]
    only_vad = AudioModels(detector=FakeDetector())  # VAD sem transcritor não roda fala
    assert [s.name for s in analysis_stages(only_vad)] == ["audio_signals", "sound_events"]


def test_pause_is_requested_by_the_models(ctx: StageContext) -> None:
    paused: list[int] = []
    paused_ctx = dataclasses.replace(ctx, wait_for_gpu=lambda: paused.append(1))
    SpeechStage(FakeDetector(), FakeTranscriber()).run(paused_ctx)
    assert len(paused) == 2  # uma vez no VAD, outra na transcrição


def test_unknown_session_is_a_clear_error(db: Session, settings: Settings) -> None:
    with pytest.raises(AnalysisError, match="Sessão 99"):
        analyze_session(db, 99, settings, AlwaysFreeGate())


@needs_ffmpeg
def test_service_stores_events_once_and_keeps_variants_apart(
    db: Session, settings: Settings, fixture_folders: dict[str, Path]
) -> None:
    from cronista.ingest.service import ingest_folder

    assert ingest_folder(db, fixture_folders["normal"], settings, AlwaysFreeGate()).ok
    session_id = db.scalars(select(RecordingSession.id)).one()
    media = db.scalars(select(MediaFile)).one()
    laugh = SoundEventSpan(label="risada", start_s=0.5, end_s=1.0, score=0.9)
    models = AudioModels(FakeDetector([(0.2, 1.5)]), FakeTranscriber("e aí"), FakeClassifier([laugh]))

    first = analyze_session(db, session_id, settings, AlwaysFreeGate(), models)
    assert first.ok and not first.skipped
    audio_events = {k: v for k, v in first.events.items() if "video_scenes" not in k}
    # fala, risada no jogo e risada no microfone (+ o detector de exclamação, que não achou nada)
    assert sorted(audio_events.values()) == [0, 1, 1, 1]
    again = analyze_session(db, session_id, settings, AlwaysFreeGate(), models)
    assert not again.files[Path(media.path).name].executed  # tudo em cache
    audio_only = select(func.count()).select_from(Event).where(Event.stage != "video_scenes")
    assert db.scalar(audio_only) == 3  # nada duplicado

    speech = load_events(db, media.id, kind="fala")
    assert [e.evidence.quote for e in speech] == ["e aí"]

    class OtherAsr(FakeTranscriber):
        name = "fake-asr-b"

    other = analyze_session(
        db,
        session_id,
        settings,
        AlwaysFreeGate(),
        AudioModels(FakeDetector([(0.2, 1.5)]), OtherAsr("e ai")),
    )
    assert other.ok
    variants = {a.variant for a in db.scalars(select(Artifact).where(Artifact.stage == "speech"))}
    assert variants == {
        "fake-vad-fake-asr",
        "fake-vad-fake-asr-b",
    }  # outro modelo: outra variante, lado a lado
    quotes = {e.evidence.model: e.evidence.quote for e in load_events(db, media.id, kind="fala")}
    assert quotes == {"fake-asr": "e aí", "fake-asr-b": "e ai"}


@needs_ffmpeg
def test_without_models_only_cpu_signals_run_and_the_report_says_what_was_skipped(
    db: Session, settings: Settings, fixture_folders: dict[str, Path]
) -> None:
    from cronista.ingest.service import ingest_folder

    ingest_folder(db, fixture_folders["normal"], settings, AlwaysFreeGate())
    session_id = db.scalars(select(RecordingSession.id)).one()
    report = analyze_session(db, session_id, settings, AlwaysFreeGate())
    audio_events = {k: v for k, v in report.events.items() if "video_scenes" not in k}
    assert report.ok and len(report.skipped) == 2 and not any(audio_events.values())
    (file_report,) = report.files.values()
    assert "audio_signals" in file_report.executed


def test_utterance_model_validates_ranges() -> None:
    with pytest.raises(ValueError):
        Utterance(text="x", start_s=-1, end_s=1)


def test_missing_master_is_a_clear_per_file_failure(db: Session, settings: Settings, tmp_path: Path) -> None:
    from cronista.db.models import Project

    project = Project(name="p")
    db.add(project)
    db.flush()
    session = RecordingSession(project_id=project.id, folder="x")
    db.add(session)
    db.flush()
    db.add(MediaFile(session_id=session.id, path=str(tmp_path / "apagado.mp4")))
    db.commit()
    report = analyze_session(db, session.id, settings, AlwaysFreeGate())
    assert not report.ok and "arquivo não encontrado" in report.failures["apagado.mp4"]


def test_long_model_names_become_a_valid_distinct_variant(ctx: StageContext) -> None:
    from cronista.pipeline.stage import make_variant, stage_variant

    long_a = "silero-vad-v5.1-onnx+faster-whisper-large-v3-turbo-int8-float16-ct2-pt-br-" + "x" * 80
    long_b = long_a + "-b"
    a, b = make_variant(long_a), make_variant(long_b)
    assert len(a) <= 100 and len(b) <= 100 and a != b  # o hash separa nomes longos parecidos
    assert make_variant("silero vad+large-v3/turbo") == "silero-vad-large-v3-turbo"
    assert make_variant("///") == "x"

    class LongName(FakeTranscriber):
        name = long_a

    stage = SpeechStage(FakeDetector(), LongName())
    assert stage_variant(stage) == stage.variant and len(stage.variant) <= 100
