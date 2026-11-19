"""Achados do `/code-review` da Fase 10 (2026-11-19): cada um começa por um teste que o reproduz."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session

from cronista.db.models import MediaFile, Project, RecordingSession
from cronista.domain.frames import FPS
from cronista.relevance.engine import Segment
from cronista.review import panel as panel_module
from cronista.review.panel import series_panel_full
from cronista.story import service as story_service
from cronista.story.models import ObjKind
from cronista.story.objectives import RuleExtractor, add_objective, current_state, discover
from tests.test_export_montagem import _plan
from tests.test_story import fala


def _one_media(db: Session) -> Project:
    project = Project(name="serie", game="g")
    db.add(project)
    db.commit()
    session = RecordingSession(project_id=project.id, folder="f")
    db.add(session)
    db.commit()
    db.add(MediaFile(session_id=session.id, path="a.mp4"))
    db.commit()
    return project


# --- 1. o limiar do perfil vale também no painel e na narrativa -------------------------------------------


def test_perfil_keep_score_vale_no_painel_da_serie(monkeypatch: pytest.MonkeyPatch, db: Session) -> None:
    _one_media(db)
    seg = Segment(0, 600, "jogo", 0.6, ["r"], [], {})  # mantido com o limiar padrão (0,35)
    monkeypatch.setattr(panel_module, "load_effective_segments", lambda _db, _media: [seg])
    padrao = series_panel_full(db).projetos[0].total_min
    exigente = series_panel_full(db, overrides={"keep_score": 0.9}).projetos[0].total_min
    assert padrao > 0 and exigente == 0


def test_perfil_keep_score_vale_no_arco_da_historia(monkeypatch: pytest.MonkeyPatch, db: Session) -> None:
    project = _one_media(db)
    seg = Segment(0, 600, "jogo", 0.6, ["r"], [], {})
    monkeypatch.setattr(story_service, "load_effective_segments", lambda _db, _media: [seg])
    mantido = story_service.build_series_story(db, project.id, 600)
    assert sum(len(c.items) for c in mantido.chapters) > 0
    exigente = story_service.build_series_story(db, project.id, 600, overrides={"keep_score": 0.9})
    assert sum(len(c.items) for c in exigente.chapters) == 0


# --- 2. marcadores no mesmo quadro nunca saem do corte -----------------------------------------------------


def test_marcadores_empilhados_no_fim_do_corte_nao_passam_dele() -> None:
    from cronista.export.montagem import MarkerInput, timeline_markers

    plan = _plan()
    first = plan.v1[0]
    last = first.out_frame - 1  # último quadro do primeiro corte
    marks = [MarkerInput(1, last, "momento", f"m{n}") for n in range(4)]
    result, skipped = timeline_markers(plan, marks)
    end = first.timeline_start + (first.out_frame - first.in_frame)
    frames = [t.frame for t in result]
    assert len(set(frames)) == len(frames)  # nunca dois no mesmo quadro
    assert all(first.timeline_start <= f < end for f in frames)  # e nenhum fora do corte de origem
    assert len(frames) + len(skipped) == 4


# --- 3. estado já gravado não bloqueia a volta a esse estado -----------------------------------------------


def test_estado_que_volta_a_ser_o_mesmo_de_antes_e_regravado(db: Session) -> None:
    project = _one_media(db)
    session = db.query(RecordingSession).one()
    obj = add_objective(db, project.id, "achar comida", ObjKind.PRINCIPAL)
    speech = [fala(50, 53, "Não consegui achar comida nenhuma.")]
    marca = [(51 * FPS, 51 * FPS)]

    def run(with_marker: bool) -> Any:
        discover(
            db, project.id, session.id, 1, speech, RuleExtractor([obj.title]),
            failure_corroboration=marca if with_marker else [],
        )  # fmt: skip
        return current_state(db, obj.id).state  # type: ignore[union-attr]

    assert run(True) == "falhou"
    assert run(False) == "incerto"  # o marcador de falha sumiu
    assert run(True) == "falhou"  # voltou: o estado vigente tem que acompanhar a evidência atual


def test_current_settings_leva_os_limiares_do_perfil_para_o_nucleo(
    monkeypatch: pytest.MonkeyPatch, settings: Any, tmp_path: Any
) -> None:
    from cronista.commands import common

    (tmp_path / "meu.yaml").write_text(
        "name: meu\nthresholds:\n  relevance:\n    keep_score: 0.8\n", encoding="utf-8"
    )
    configured = settings.model_copy(update={"profile": "meu", "profiles_dir": tmp_path})
    monkeypatch.setattr(common, "load_settings", lambda: configured)
    assert common.current_settings().relevance_overrides == {"keep_score": 0.8}

    broken = settings.model_copy(update={"profile": "nao-existe", "profiles_dir": tmp_path})
    monkeypatch.setattr(common, "load_settings", lambda: broken)
    assert common.current_settings().relevance_overrides is None  # perfil que não carrega não derruba o resto
