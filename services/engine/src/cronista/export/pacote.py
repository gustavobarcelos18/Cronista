"""Pacote de exportação (Fase 6C): `versao-N/` com FCPXML, SRT, Lua de marcadores, stems e manifesto.

Reexportar cria uma versão nova; nunca apaga a anterior (o criador pode já ter importado a velha no Resolve).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.assembly.service import build_assembly
from cronista.config import Settings
from cronista.db.models import Marker, RecordingSession
from cronista.export.montagem import (
    ExportMedia,
    MarkerInput,
    MediaFileInfo,
    check_plan_fcpxml,
    marker_lua,
    render_plan_fcpxml,
    render_timeline_srt,
    timeline_markers,
)
from cronista.export.timelapse import render_timelapses
from cronista.logging_setup import log_event
from cronista.mix.service import MixReport, mix_session
from cronista.montage import _load_source
from cronista.story.models import Script
from cronista.story.service import DEFAULT_TARGET_S

PLAN_VERSION = 1
LEIA_ME = """# Importar no DaVinci Resolve (gratuito)

Projeto novo: **1920x1080, 60 fps** (Master Settings → Timeline frame rate = 60, e não 59,94).

1. Arquivo → Importar → Linha de Tempo → `montagem.fcpxml`. A mídia vem linkada pelo caminho dos masters; se o
   Resolve pedir, aponte a pasta dos masters (relink).
2. Marcadores coloridos: abra Área de Trabalho → Console (Lua), cole **uma linha de cada vez** de
   `marcadores-N.lua` e dê Enter. Cada uma imprime quantos marcadores adicionou.
3. Legenda do roteiro: Arquivo → Importar → Legenda → `roteiro.srt`, e arraste o item do Pool para a timeline
   (o SRT tem uma fala "." em 0 s de propósito, para não deslocar as demais).
4. Cartelas "Capítulo N" estão na V5 como título editável: troque o texto por "Dia N" ao decidir os dias.
5. A1 e A2 são os stems mixados; A6 e A7, os crus (inativos): para desfazer a mixagem, troque um pelo outro.

Importação, trilhas e marcadores ainda dependem do spike do Resolve (plano, seção 6.5); anote o que falhar.
"""


@dataclass
class PackageReport:
    directory: Path
    version: int
    clips: int
    duration_s: float
    markers: int
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mix: MixReport | None = None


def next_version_dir(base: Path) -> tuple[Path, int]:
    existing = [
        int(m.group(1)) for p in base.glob("versao-*") if (m := re.fullmatch(r"versao-(\d+)", p.name))
    ]
    version = max(existing, default=0) + 1
    return base / f"versao-{version}", version


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_montagem(
    db: Session,
    session_id: int,
    settings: Settings,
    script: Script | None = None,
    target_s: float = DEFAULT_TARGET_S,
    profile_objectives: tuple[list[str], list[str]] = ([], []),
    out_base: Path | None = None,
) -> PackageReport:
    base = out_base or settings.data_dir / "export" / "montagem" / str(session_id)
    directory, version = next_version_dir(base)
    directory.mkdir(parents=True)

    plan = build_assembly(db, session_id, settings, target_s, profile_objectives)
    session = db.get(RecordingSession, session_id)
    assert session is not None  # build_assembly já validou
    sources = {m.id: _load_source(db, m) for m in session.media_files}
    masters = {fid: s.master for fid, s in sources.items()}

    timelapses = render_timelapses(plan, masters, directory / "timelapses", settings)
    mix = mix_session(
        db, session_id, settings, script, target_s, profile_objectives, directory / "stems", plan=plan
    )
    stems = {
        "A1": directory / "stems" / "A1-jogo.wav",
        "A2": directory / "stems" / "A2-voz.wav",
        "A6": directory / "stems" / "A6-jogo-cru.wav",
        "A7": directory / "stems" / "A7-microfone-cru.wav",
    }
    media = ExportMedia(
        masters={
            fid: MediaFileInfo(s.master, round(s.duration_s * 60) if s.duration_s is not None else None)
            for fid, s in sources.items()
        },
        timelapses=timelapses,
        stems=stems,
        stem_frames=plan.total_frames,
    )

    fcpxml = render_plan_fcpxml(plan, media, f"sessao-{session_id}-v{version}")
    fcpxml_path = directory / "montagem.fcpxml"
    fcpxml_path.write_text(fcpxml, encoding="utf-8")
    problems = check_plan_fcpxml(fcpxml, plan)

    srt_path = directory / "roteiro.srt"
    srt_path.write_text(render_timeline_srt(plan, script.lines if script else []), encoding="utf-8")

    marks = [
        MarkerInput(m.media_file_id, m.media_frame, m.kind, m.marker_id)
        for m in db.scalars(select(Marker).where(Marker.session_id == session_id))
        if m.media_file_id is not None
    ]
    timeline_marks, skipped = timeline_markers(plan, marks)
    lua_files: list[Path] = []
    for n, line in enumerate(marker_lua(timeline_marks), start=1):
        path = directory / f"marcadores-{n}.lua"
        path.write_text(line + "\n", encoding="utf-8")
        lua_files.append(path)

    (directory / "plano-montagem.json").write_text(plan.to_json(), encoding="utf-8")
    (directory / "LEIA-ME.md").write_text(LEIA_ME, encoding="utf-8")
    warnings = [*plan.warnings, *mix.warnings, *skipped]
    manifest = {
        "versao": version,
        "versao_do_plano": PLAN_VERSION,
        "sessao": session_id,
        "fps": 60,
        "duracao_s": round(plan.total_s, 2),
        "cortes_v1": len(plan.v1),
        "marcadores": len(timeline_marks),
        "arquivos": {p.name: _sha(p) for p in [fcpxml_path, srt_path, *lua_files]},
        "stems": {k: v.name for k, v in stems.items()},
        "problemas": problems,
        "avisos": warnings,
    }
    (directory / "manifesto.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    log_event("montagem_exportada", session_id=session_id, version=version, path=str(directory))
    return PackageReport(
        directory, version, len(plan.v1), plan.total_s, len(timeline_marks), problems, warnings, mix
    )
