"""Correções do /code-review da Fase 10: overrides tipados, `aceito` que força o trecho, âncora fixa."""

from __future__ import annotations

from sqlalchemy.orm import Session

from cronista.audio.events import replace_events
from cronista.db.models import MediaFile, Project, RecordingSession
from cronista.relevance.engine import RelevanceParams, Segment, is_kept
from cronista.relevance.service import segments_to_events
from cronista.review.decisions import load_effective_segments, record_decision
from cronista.review.learning import params_for_project
from cronista.story.service import anchor_session


def test_overrides_do_perfil_mantem_o_tipo_dos_campos(db: Session) -> None:
    params = params_for_project(db, 1, {"max_s": 120.0, "min_s": 6.0, "keep_score": 0.4, "desconhecido": 1.0})
    assert params.max_s == 120 and isinstance(params.max_s, int)
    assert params.min_s == 6 and isinstance(params.min_s, int)
    assert params.keep_score == 0.4
    # Os campos `int` seguem fatiáveis (`speech[lo:hi]` na segmentação).
    assert list(range(300))[params.max_s // 2 : params.max_s] == list(range(60, 120))


def test_aceito_e_ajustado_forcam_o_trecho_mesmo_com_nota_baixa(db: Session) -> None:
    project = Project(name="serie")
    session = RecordingSession(project=project, folder="pasta")
    media = MediaFile(session=session, path="C:/x/a.mp4", ordinal=0, size_bytes=10)
    db.add_all([project, session, media])
    db.flush()
    segs = [
        Segment(0, 30, "conversa", 0.2),
        Segment(100, 130, "conversa", 0.2),
        Segment(200, 230, "conversa", 0.2),
    ]
    replace_events(db, media.id, "relevance", "", segments_to_events(segs, RelevanceParams()))
    assert not any(is_kept(s) for s in segs)

    record_decision(db, media.id, 0, "aceito")
    record_decision(db, media.id, 100, "ajustado", 100, 120)
    effective = {s.start_s: s for s in load_effective_segments(db, media.id)}
    assert is_kept(effective[0]) and is_kept(effective[100])
    assert not is_kept(effective[200])  # sem decisão vale a regra normal


def test_ancora_da_serie_nao_muda_quando_entra_sessao_nova(db: Session) -> None:
    project = Project(name="serie")
    first = RecordingSession(project=project, folder="a")
    db.add_all([project, first])
    db.commit()
    assert anchor_session(db, project.id).id == first.id
    db.add(RecordingSession(project=project, folder="b"))
    db.commit()
    assert anchor_session(db, project.id).id == first.id
