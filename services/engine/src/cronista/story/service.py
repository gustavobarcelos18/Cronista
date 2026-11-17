"""Narrativa de uma sessão: junta banco (eventos, marcadores, segmentos, objetivos) e gera o story-pack."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.audio.events import load_active_events
from cronista.db.models import Marker, Objective, RecordingSession
from cronista.domain.evidence import AnalysisEvent
from cronista.relevance.engine import Segment
from cronista.review.decisions import load_effective_segments
from cronista.story.arc import Chapter, allocate_time, build_chapters
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
from cronista.story.script import ValidationReport, to_srt, validate_script, voice_profile

DEFAULT_TARGET_S = 40 * 60.0


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
) -> StoryResult:
    session = db.get(RecordingSession, session_id)
    if session is None:
        raise StoryError(f"sessão {session_id} não existe (veja `cronista status`)")
    project = session.project
    sync_profile_objectives(db, project.id, *profile_objectives)

    files: list[tuple[int, list[Segment]]] = []
    speech_by_file: dict[int, list[AnalysisEvent]] = {}
    kinds: dict[str, str] = {}
    discovery = DiscoveryReport()
    known = [o.title for o in db.scalars(select(Objective).where(Objective.project_id == project.id))]
    for media in sorted(session.media_files, key=lambda m: m.ordinal):
        segments = load_effective_segments(db, media.id)
        if not segments:
            continue
        files.append((media.id, segments))
        events = load_active_events(db, media.id)
        speech = speech_events([e for e in events if e.kind == "fala"])
        speech_by_file[media.id] = speech
        marks = list(db.scalars(select(Marker).where(Marker.media_file_id == media.id)))
        kinds.update({m.marker_id: m.kind for m in marks})
        corroboration = [(m.media_frame, m.media_frame) for m in marks if m.kind == "conquista"]
        failures = [(m.media_frame, m.media_frame) for m in marks if m.kind == "morte_falha"]
        part = discover(
            db, project.id, session_id, media.id, speech, RuleExtractor(known), corroboration, failures
        )
        discovery.confirmed += part.confirmed
        discovery.hypotheses += part.hypotheses
        discovery.rejected += part.rejected
    if not files:
        raise StoryError("sem segmentos; rode `cronista relevance` antes")

    chapters = build_chapters(files, kinds)
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
        chapters, speech_by_file, {"nome": project.name, "jogo": project.game}, objectives, target_s
    )
    quotes = [e.evidence.quote or "" for sp in speech_by_file.values() for e in sp]
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
    pack_path = directory / "story-pack.json"
    pack_path.write_text(json.dumps(result.pack, ensure_ascii=False, indent=1), encoding="utf-8")
    voice_path = directory / "voice-profile.json"
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
    pack_path = folder / "story-pack.json"
    if not pack_path.is_file():
        raise ScriptSaveError("rode `cronista story` antes")
    index = segment_index(json.loads(pack_path.read_text(encoding="utf-8")))
    report = validate_script(script, index)
    if not report.ok:
        raise ScriptSaveError("roteiro inválido", report.errors)
    current = folder / "roteiro.json"
    saved = script.model_copy(update={"lines": report.lines})
    starts = {sid: gaps[0][0] if gaps else a for sid, (a, _b, gaps) in index.items()}
    # Grava o novo em arquivos temporários ANTES de mexer no atual: se a escrita falhar, o roteiro vigente
    # continua no lugar e o histórico não fica com buraco.
    tmp_json, tmp_srt = folder / "roteiro.json.tmp", folder / "roteiro.srt.tmp"
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
