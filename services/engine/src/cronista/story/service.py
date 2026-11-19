"""Narrativa de uma sessão: junta banco (eventos, marcadores, segmentos, objetivos) e gera o story-pack."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.audio.events import load_active_events
from cronista.db.models import Marker, Objective, Project, RecordingSession
from cronista.domain.evidence import AnalysisEvent
from cronista.paths import SCRIPT, STORY_PACK, VOICE_PROFILE
from cronista.relevance.engine import Segment
from cronista.review.decisions import load_effective_segments
from cronista.review.learning import params_for_project
from cronista.story.arc import Chapter, allocate_time, chapters_from_files
from cronista.story.models import Script
from cronista.story.objectives import (
    DiscoveryReport,
    RuleExtractor,
    current_state,
    discover,
    speech_events,
    sync_profile_objectives,
)
from cronista.story.pack import build_story_pack
from cronista.story.script import (
    CLOSE_ID,
    HOOK_ID,
    LIVE_KINDS,
    ValidationReport,
    to_srt,
    validate_script,
    voice_profile,
)

DEFAULT_TARGET_MIN = 40.0
MAX_TARGET_MIN = 240.0
DEFAULT_TARGET_S = DEFAULT_TARGET_MIN * 60


class StoryError(Exception):
    pass


@dataclass
class StoryResult:
    chapters: list[Chapter]
    pack: dict[str, Any]
    discovery: DiscoveryReport = field(default_factory=DiscoveryReport)
    voice: dict[str, Any] = field(default_factory=dict)


def build_story(
    db: Session,
    session_id: int,
    target_s: float = DEFAULT_TARGET_S,
    profile_objectives: tuple[list[str], list[str]] = ([], []),
    overrides: Mapping[str, float] | None = None,
) -> StoryResult:
    """História de **uma** sessão, com o alvo inteiro. Para o vídeo da série use `build_series_story`."""
    session = db.get(RecordingSession, session_id)
    if session is None:
        raise StoryError(f"sessão {session_id} não existe (veja `cronista status`)")
    return _build(db, session.project, [session], target_s, profile_objectives, overrides)


def build_series_story(
    db: Session,
    project_id: int,
    target_s: float = DEFAULT_TARGET_S,
    profile_objectives: tuple[list[str], list[str]] = ([], []),
    overrides: Mapping[str, float] | None = None,
) -> StoryResult:
    """História do vídeo da série (plano 4.1): todas as sessões do projeto, em ordem, com **um** alvo.

    Um marcador `novo_dia` abre um capítulo, então um dia que atravessa duas sessões
    continua sendo um capítulo só. Os ids dos segmentos (`arquivo:início`) já são únicos entre sessões.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise StoryError(f"projeto {project_id} não existe (veja `cronista status`)")
    sessions = scope_sessions(db, None, project_id)
    return _build(db, project, sessions, target_s, profile_objectives, overrides)


def scope_sessions(db: Session, session_id: int | None, project_id: int | None) -> list[RecordingSession]:
    """Sessões do escopo: uma sessão, ou todas as do projeto (vídeo da série), em ordem."""
    if (session_id is None) == (project_id is None):
        raise StoryError("informe a sessão ou o projeto (um dos dois)")
    if project_id is not None:
        sessions = list(
            db.scalars(
                select(RecordingSession)
                .where(RecordingSession.project_id == project_id)
                .order_by(RecordingSession.id)
            )
        )
        if not sessions:
            raise StoryError(f"projeto {project_id} não tem sessões")
        return sessions
    session = db.get(RecordingSession, session_id or 0)
    if session is None:
        raise StoryError(f"sessão {session_id} não existe (veja `cronista status`)")
    return [session]


def anchor_session(db: Session, project_id: int) -> RecordingSession:
    """Sessão âncora do vídeo da série: a primeira do projeto (a que não muda quando entram sessões novas).

    O vídeo único não tem tabela própria; o roteiro, os títulos, as thumbnails e os Shorts dele moram nas
    pastas (e nas linhas) da sessão âncora, e todos os comandos por sessão funcionam passando o id dela.
    """
    return scope_sessions(db, None, project_id)[0]


def _build(
    db: Session,
    project: Project,
    sessions: list[RecordingSession],
    target_s: float,
    profile_objectives: tuple[list[str], list[str]],
    overrides: Mapping[str, float] | None = None,
) -> StoryResult:
    sync_profile_objectives(db, project.id, *profile_objectives)

    files: list[tuple[int, list[Segment], dict[str, str]]] = []
    speech_by_file: dict[int, list[AnalysisEvent]] = {}
    discovery = DiscoveryReport()
    ordered = [m for session in sessions for m in sorted(session.media_files, key=lambda m: m.ordinal)]
    for media in ordered:
        segments = load_effective_segments(db, media.id)
        if not segments:
            continue
        events = load_active_events(db, media.id)
        speech = speech_events([e for e in events if e.kind == "fala"])
        # Para as lacunas valem também risada, exclamação e voz sem texto: a narração não pode cobri-las.
        speech_by_file[media.id] = [e for e in events if e.kind in LIVE_KINDS]
        marks = list(db.scalars(select(Marker).where(Marker.media_file_id == media.id)))
        files.append((media.id, segments, {m.marker_id: m.kind for m in marks}))
        corroboration = [(m.media_frame, m.media_frame) for m in marks if m.kind == "conquista"]
        failures = [(m.media_frame, m.media_frame) for m in marks if m.kind == "morte_falha"]
        # Os objetivos mudam a cada arquivo (o anterior pode propor um novo): lê de novo antes de cada um.
        known = [o.title for o in db.scalars(select(Objective).where(Objective.project_id == project.id))]
        part = discover(
            db, project.id, media.session_id, media.id, speech, RuleExtractor(known), corroboration, failures
        )
        discovery.confirmed += part.confirmed
        discovery.hypotheses += part.hypotheses
        discovery.rejected += part.rejected
    if not files:
        raise StoryError("sem segmentos; rode `cronista relevance` antes")

    chapters = chapters_from_files(files, params_for_project(db, project.id, overrides).keep_score)
    allocate_time(chapters, target_s)
    objectives = []
    for obj in db.scalars(select(Objective).where(Objective.project_id == project.id)):
        st = current_state(db, obj.id)
        objectives.append(
            {
                "id": obj.id,
                "titulo": obj.title,
                "tipo": obj.kind,
                "estado": st.state if st else "sem_estado",
                "citacao": (st.ev_quote or "")[:160] if st else "",
                "confirmado": bool(st and st.state not in ("proposto", "incerto")),
            }
        )
    pack = build_story_pack(
        chapters, speech_by_file, {"nome": project.name, "jogo": project.game or ""}, objectives, target_s
    )
    quotes = [e.evidence.quote or "" for sp in speech_by_file.values() for e in sp if e.kind == "fala"]
    return StoryResult(chapters, pack, discovery, voice_profile(quotes))


def segment_index(pack: dict[str, Any]) -> dict[str, tuple[float, float, list[tuple[float, float]]]]:
    """Segmentos do pacote para a validação do roteiro: id → (início, fim, espaços livres)."""
    out: dict[str, tuple[float, float, list[tuple[float, float]]]] = {}
    for chapter in pack.get("capitulos", []):
        for b in chapter.get("beats", []):
            out[b["segmento_id"]] = (
                float(b["inicio_s"]),
                float(b["fim_s"]),
                [(g["inicio_s"], g["fim_s"]) for g in b.get("lacunas", [])],
            )
    return out


def write_pack(directory: Path, result: StoryResult) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    pack_path = directory / STORY_PACK
    pack_path.write_text(json.dumps(result.pack, ensure_ascii=False, indent=1), encoding="utf-8")
    voice_path = directory / VOICE_PROFILE
    voice_path.write_text(json.dumps(result.voice, ensure_ascii=False, indent=1), encoding="utf-8")
    return pack_path, voice_path


class ScriptSaveError(Exception):
    """Roteiro não pôde ser salvo: sem story-pack ou com erros de validação."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


def save_script(folder: Path, script: Script) -> ValidationReport:
    """Valida o roteiro contra o story-pack da pasta e grava `roteiro.json` + `roteiro.srt`.

    A versão anterior nunca se perde: vira `roteiro.v<N>.json` (histórico só de inserção). Com erros de
    validação nada é gravado.
    """
    pack_path = folder / STORY_PACK
    if not pack_path.is_file():
        raise ScriptSaveError("rode `cronista story` antes")
    index = segment_index(json.loads(pack_path.read_text(encoding="utf-8")))
    report = validate_script(script, index)
    if not report.ok:
        raise ScriptSaveError("roteiro inválido", report.errors)
    current = folder / SCRIPT
    saved = script.model_copy(update={"lines": report.lines})
    starts = {sid: gaps[0][0] if gaps else a for sid, (a, _b, gaps) in index.items()}
    if index:  # janelas reservadas em tempo de arquivo: gancho no começo do 1º trecho, fecho no fim do último
        close_total = sum(x.est_s or 0.0 for x in report.lines if x.segment_id == CLOSE_ID)
        starts[HOOK_ID] = min(a for a, _b, _g in index.values())
        starts[CLOSE_ID] = max(b for _a, b, _g in index.values()) - close_total
    # Grava o novo em arquivos temporários ANTES de mexer no atual: se a escrita falhar, o roteiro vigente
    # continua no lugar e o histórico não fica com buraco.
    tmp_json, tmp_srt = folder / f"{SCRIPT}.tmp", folder / "roteiro.srt.tmp"
    tmp_json.write_text(saved.model_dump_json(indent=1), encoding="utf-8")
    tmp_srt.write_text(to_srt(report.lines, starts), encoding="utf-8")
    if current.is_file():
        n = 1
        while (folder / f"roteiro.v{n}.json").exists():
            n += 1
        current.replace(folder / f"roteiro.v{n}.json")
    tmp_json.replace(current)
    tmp_srt.replace(folder / "roteiro.srt")
    return report
