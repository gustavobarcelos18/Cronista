"""Pacote de exportação (Fase 6C): `versao-N/` com FCPXML, SRT, Lua de marcadores, stems e manifesto.

Reexportar cria uma versão nova; nunca apaga a anterior (o criador pode já ter importado a velha no Resolve).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.assembly.plan import EditPlan
from cronista.assembly.service import assemble
from cronista.config import Settings
from cronista.db.models import Marker
from cronista.domain.frames import FPS, duration_frames
from cronista.export.montagem import (
    ExportMedia,
    MarkerInput,
    MediaFileInfo,
    TimelineMarker,
    check_plan_fcpxml,
    marker_lua,
    render_plan_fcpxml,
    render_timeline_srt,
    timeline_markers,
)
from cronista.export.timelapse import render_timelapses
from cronista.finishing.apply import FinishArtifacts, apply_finishing, inputs_digest, leia_me_section
from cronista.finishing.brand import ResolvedStyle, brand_dir
from cronista.finishing.library import Library
from cronista.finishing.markers import suggestion_markers
from cronista.finishing.plan import FinishPlan, apply_decisions
from cronista.finishing.service import finish_from_edit_plan, marker_kinds_by_segment, marker_peaks
from cronista.logging_setup import log_event
from cronista.mix.service import MixReport, mix_session
from cronista.montage import load_source
from cronista.paths import SessionPaths, series_package_base
from cronista.pipeline.gpu import GpuGate, wait_until_free
from cronista.story.models import Script
from cronista.story.service import DEFAULT_TARGET_S, scope_sessions

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
6. Se o pacote tem `acabamento.json`, os efeitos em modo "sugerir" chegam como marcadores "Sugestão: ..."
   (no mesmo Lua dos marcadores); aplicar é decisão sua. Os aplicados pelo app vêm nas trilhas V2, V4, A4 e A5
   do FCPXML, descritos na seção "Acabamento" abaixo.

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
    reused: bool = False  # True: nada mudou desde a última versão completa, então nada foi regerado


def _version_numbers(base: Path) -> list[int]:
    return sorted(
        int(m.group(1)) for p in base.glob("versao-*") if (m := re.fullmatch(r"versao-(\d+)", p.name))
    )


def input_hash(
    plan: EditPlan, script: Script | None, finish: FinishPlan | None = None, finish_inputs: str = ""
) -> str:
    """Identifica a entrada da exportação: o mesmo plano e roteiro geram o mesmo pacote."""
    h = hashlib.sha256()
    h.update(str(PLAN_VERSION).encode())
    h.update(plan.to_json().encode())
    h.update((script.model_dump_json() if script else "").encode())
    if finish is not None:  # sem acabamento o hash continua igual ao das versões anteriores
        h.update(b"acabamento")
        h.update(finish.to_json().encode())
        h.update(finish_inputs.encode())  # brand kit e arquivos que mudam o render sem mudar o plano
    return h.hexdigest()


def _resume_target(base: Path, digest: str) -> tuple[Path, int, PackageReport | None]:
    """Versão idêntica e completa → reaproveita; interrompida → continua nela; senão, versão nova."""
    versions = _version_numbers(base)
    if versions:
        last = base / f"versao-{versions[-1]}"
        manifest_path = last / "manifesto.json"
        if not manifest_path.is_file():
            return last, versions[-1], None
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("entrada_hash") == digest and not manifest.get("problemas"):
            report = PackageReport(
                last,
                versions[-1],
                manifest["cortes_v1"],
                manifest["duracao_s"],
                manifest["marcadores"],
                [],
                list(manifest.get("avisos", [])),
                None,
                True,
            )
            return last, versions[-1], report
    directory, version = next_version_dir(base)
    return directory, version, None


def next_version_dir(base: Path) -> tuple[Path, int]:
    version = max(_version_numbers(base), default=0) + 1
    return base / f"versao-{version}", version


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_montagem(
    db: Session,
    session_id: int | None,
    settings: Settings,
    script: Script | None = None,
    target_s: float = DEFAULT_TARGET_S,
    profile_objectives: tuple[list[str], list[str]] = ([], []),
    out_base: Path | None = None,
    gate: GpuGate | None = None,
    style: ResolvedStyle | None = None,
    library: Library | None = None,
    finish_decisions: Mapping[str, str] | None = None,
    project_id: int | None = None,
) -> PackageReport:
    """Com `style` (brand kit + série), o pacote leva também o plano de acabamento (Fase 8).

    `finish_decisions` são as decisões do criador no Studio por `id` de item (`aceito`/`removido`).
    """
    sessions = scope_sessions(db, session_id, project_id)
    session_ids = [s.id for s in sessions] if project_id is not None else [session_id or 0]
    scope_label = f"serie-{project_id}" if project_id is not None else f"sessao-{session_id}"
    base = out_base or (
        series_package_base(settings, project_id)
        if project_id is not None
        else SessionPaths.of(settings, session_id or 0).package_base
    )
    plan, story = assemble(db, session_id, settings, target_s, profile_objectives, None, project_id)
    finish = (
        finish_from_edit_plan(
            plan, marker_kinds_by_segment(story.chapters), style, library, marker_peaks(db, session_ids)
        )
        if style is not None
        else None
    )
    if finish is not None and finish_decisions:
        finish = apply_decisions(finish, finish_decisions)
    brand_directory = brand_dir(settings.brand_dir)
    inputs = (
        inputs_digest(finish, style, brand_directory, library, settings.library_dir)
        if finish is not None and style is not None
        else ""
    )
    digest = input_hash(plan, script, finish, inputs)
    directory, version, done = _resume_target(base, digest)
    if done is not None:
        log_event("montagem_reaproveitada", session_id=session_id, project_id=project_id, version=version)
        return done
    directory.mkdir(parents=True, exist_ok=True)

    def wait(stage: str) -> None:
        if gate is not None:
            wait_until_free(gate, settings.gpu_poll_seconds, etapa=stage)

    sources = {m.id: load_source(db, m) for s in sessions for m in s.media_files}
    masters = {fid: s.master for fid, s in sources.items()}

    # Os timelapses ficam na base (não na versão): versões novas reaproveitam o que já foi renderizado.
    timelapses = render_timelapses(plan, masters, base / "timelapses", settings, gate)
    wait("mixagem")
    mix = mix_session(
        db,
        session_id,
        settings,
        script,
        target_s,
        profile_objectives,
        directory / "stems",
        plan=plan,
        project_id=project_id,
    )
    stems = {
        "A1": directory / "stems" / "A1-jogo.wav",
        "A2": directory / "stems" / "A2-voz.wav",
        "A6": directory / "stems" / "A6-jogo-cru.wav",
        "A7": directory / "stems" / "A7-microfone-cru.wav",
    }
    artifacts: FinishArtifacts | None = None
    if finish is not None and style is not None:
        artifacts = apply_finishing(
            finish,
            plan,
            masters,
            style,
            library,
            settings,
            base,
            directory,
            brand_directory,
            gate,
        )
        if artifacts.music_stem is not None:
            stems["A4"] = artifacts.music_stem
    media = ExportMedia(
        masters={
            fid: MediaFileInfo(s.master, duration_frames(s.duration_s) if s.duration_s is not None else None)
            for fid, s in sources.items()
        },
        timelapses=timelapses,
        stems=stems,
        stem_frames=plan.total_frames,
    )

    fcpxml = render_plan_fcpxml(
        plan, media, f"{scope_label}-v{version}", artifacts.layers if artifacts else None
    )
    fcpxml_path = directory / "montagem.fcpxml"
    fcpxml_path.write_text(fcpxml, encoding="utf-8")
    problems = check_plan_fcpxml(fcpxml, plan)

    srt_path = directory / "roteiro.srt"
    srt_path.write_text(render_timeline_srt(plan, script.lines if script else []), encoding="utf-8")

    marks = [
        MarkerInput(m.media_file_id, m.media_frame, m.kind, m.marker_id)
        for m in db.scalars(select(Marker).where(Marker.session_id.in_(session_ids)))
        if m.media_file_id is not None
    ]
    timeline_marks, skipped = timeline_markers(plan, marks)
    if finish is not None:
        timeline_marks = sorted(
            [
                *timeline_marks,
                *(
                    TimelineMarker(s.frame, s.color, s.name, s.note, s.custom)
                    for s in suggestion_markers(finish)
                ),
            ],
            key=lambda t: (t.frame, t.custom),
        )
    lua_files: list[Path] = []
    for n, line in enumerate(marker_lua(timeline_marks), start=1):
        path = directory / f"marcadores-{n}.lua"
        path.write_text(line + "\n", encoding="utf-8")
        lua_files.append(path)

    (directory / "plano-montagem.json").write_text(plan.to_json(), encoding="utf-8")
    guide = LEIA_ME + (leia_me_section(finish, artifacts) if finish is not None and artifacts else "")
    (directory / "LEIA-ME.md").write_text(guide, encoding="utf-8")
    if finish is not None:
        (directory / "acabamento.json").write_text(finish.to_json(), encoding="utf-8")
    warnings = [
        *plan.warnings,
        *mix.warnings,
        *skipped,
        *(finish.warnings if finish else []),
        *(artifacts.warnings if artifacts else []),
    ]
    manifest = {
        "versao": version,
        "versao_do_plano": PLAN_VERSION,
        "sessao": session_id,
        "projeto": project_id,
        "entrada_hash": digest,
        "fps": FPS,
        "duracao_s": round(plan.total_s, 2),
        "cortes_v1": len(plan.v1),
        "marcadores": len(timeline_marks),
        "arquivos": {p.name: _sha(p) for p in [fcpxml_path, srt_path, *lua_files]},
        "stems": {k: v.name for k, v in stems.items()},
        "acabamento": finish.summary() if finish else None,
        "efeitos": artifacts.effects if artifacts else [],
        "problemas": problems,
        "avisos": warnings,
    }
    (directory / "manifesto.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    log_event(
        "montagem_exportada",
        session_id=session_id,
        project_id=project_id,
        version=version,
        path=str(directory),
    )
    return PackageReport(
        directory, version, len(plan.v1), plan.total_s, len(timeline_marks), problems, warnings, mix
    )
