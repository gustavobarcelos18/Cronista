"""Caso de uso `cronista analyze <sessão>`: análise de áudio de cada arquivo da sessão."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from cronista.audio.events import events_from_result, replace_events
from cronista.audio.ports import AudioModels
from cronista.audio.stages import analysis_stages
from cronista.config import Settings
from cronista.db.models import RecordingSession
from cronista.ingest.stages import ingest_stages
from cronista.pipeline import GpuGate, StageFailedError, run_pipeline
from cronista.pipeline.runner import PipelineReport
from cronista.pipeline.stage import Stage, stage_key, stage_variant
from cronista.video.ports import VideoModels
from cronista.video.stages import video_stages


class AnalysisError(Exception):
    """Falha esperada do `analyze` (sessão inexistente, por exemplo)."""


@dataclass
class AnalysisReport:
    session_id: int
    files: dict[str, PipelineReport] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    events: dict[str, int] = field(default_factory=dict)  # `arquivo::etapa[:variante]` → eventos gravados
    skipped: list[str] = field(default_factory=list)  # o que não rodou e por quê

    @property
    def ok(self) -> bool:
        return not self.failures


def analyze_session(
    db: Session,
    session_id: int,
    settings: Settings,
    gate: GpuGate,
    models: AudioModels | None = None,
    only: str | None = None,
    video_models: VideoModels | None = None,
) -> AnalysisReport:
    """Roda as etapas de análise (áudio e vídeo) em cada arquivo e grava os eventos no banco.

    `only` = `audio` ou `video` limita a análise a um dos dois; sem ele roda os dois.

    As etapas de ingestão entram na lista só para fornecerem os WAVs (vêm do cache). Cada etapa com eventos
    substitui no banco os eventos da sua própria execução, então repetir o comando não duplica nada.
    """
    if only not in (None, "audio", "video"):
        raise AnalysisError(f"--only deve ser 'audio' ou 'video' (veio '{only}')")
    session = db.get(RecordingSession, session_id)
    if session is None:
        raise AnalysisError(f"Sessão {session_id} não existe (veja `cronista status`)")
    models = models or AudioModels()
    report = AnalysisReport(session_id=session_id)
    if only != "video" and (models.detector is None or models.transcriber is None):
        report.skipped.append("fala (sem detector de voz e transcritor nesta máquina)")
    if only != "video" and models.classifier is None:
        report.skipped.append("eventos sonoros (sem classificador nesta máquina)")

    analysis: list[Stage] = [
        *([] if only == "video" else analysis_stages(models)),
        *([] if only == "audio" else video_stages(video_models, with_audio=only is None)),
    ]
    stages = [*ingest_stages(), *analysis]
    for media in session.media_files:
        name = Path(media.path).name
        if not Path(media.path).is_file():
            report.failures[name] = f"arquivo não encontrado: {media.path} (movido ou apagado?)"
            continue
        try:
            result = run_pipeline(db, media, stages, settings, gate)
        except StageFailedError as exc:
            report.failures[name] = str(exc)
            continue
        report.files[name] = result
        for stage in analysis:
            events = events_from_result(result.results[stage_key(stage)])
            if events is not None:
                count = replace_events(db, media.id, stage.name, stage_variant(stage), events)
                report.events[f"{name}::{stage_key(stage)}"] = count
    return report
