from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cronista.api.app import create_app
from cronista.audio.events import replace_events
from cronista.config import Settings
from cronista.db.models import MediaFile, Project, RecordingSession
from cronista.relevance.engine import RelevanceParams, Segment
from cronista.relevance.service import segments_to_events
from cronista.review.decisions import record_decision
from cronista.review.learning import accept, defaults, params_for_project, propose


def _seed(db: Session, n: int = 30) -> None:
    """O criador mantém trechos com marcador e tira os que têm muita pausa (sinais separáveis)."""
    project = Project(name="serie")
    session = RecordingSession(project=project, folder="pasta")
    media = MediaFile(session=session, path="C:/x/a.mp4", ordinal=0, size_bytes=10)
    db.add_all([project, session, media])
    db.flush()
    segs = []
    for i in range(n):
        keep = i % 2 == 0
        feats = {
            "marcador": 1.0 if keep else 0.0,
            "emocao": 0.5,
            "fala": 0.5,
            "novidade": 0.0,
            "pausa": 0.0 if keep else 0.9,
        }
        segs.append(Segment(i * 100, i * 100 + 20, "momento", 0.5, [], [], feats))
    replace_events(db, media.id, "relevance", "", segments_to_events(segs, RelevanceParams()))
    for i in range(n):
        record_decision(db, media.id, i * 100, "aceito" if i % 2 == 0 else "rejeitado")


def test_poucas_decisoes_nao_propoem(db: Session) -> None:
    _seed(db, n=6)
    assert propose(db, 1) is None


def test_proposta_sobe_marcador_e_penalidade_com_explicacao(db: Session) -> None:
    _seed(db)
    p = propose(db, 1)
    assert p is not None and (p.kept, p.removed) == (15, 15)
    base = defaults()
    assert p.weights["w_marker"] > base["w_marker"]
    assert p.weights["w_pause"] > base["w_pause"]
    assert p.weights["w_speech"] < base["w_speech"]
    assert any(line.startswith("marcador: sobe") for line in p.explanation)


def test_menos_decisoes_ficam_mais_perto_do_padrao(tmp_path: Path) -> None:
    from cronista.db.session import open_db

    shift = {}
    for n in (20, 60):
        with open_db(tmp_path / f"db{n}.sqlite") as session:
            _seed(session, n=n)
            p = propose(session, 1)
            assert p is not None
            shift[n] = p.weights["w_marker"] - defaults()["w_marker"]
    assert 0 < shift[20] < shift[60]


def test_aceitar_vale_na_proxima_relevancia(db: Session) -> None:
    _seed(db)
    assert params_for_project(db, 1) == RelevanceParams()
    proposal = propose(db, 1)
    assert proposal is not None
    accept(db, 1, proposal)
    assert params_for_project(db, 1).w_marker == proposal.weights["w_marker"]
    assert params_for_project(db, 1).keep_score == RelevanceParams().keep_score  # só os pesos mudam


def test_api_aprendizado_e_feedback(settings: Settings, db: Session) -> None:
    _seed(db, n=6)
    client = TestClient(create_app(settings))
    assert client.get("/sessions").json()[0]["project_id"] == 1
    out = client.get("/projects/1/learning").json()
    assert out["weights"] is None and out["needed"] == 20
    assert client.post("/projects/1/learning/accept").status_code == 409
    assert client.get("/projects/99/learning").status_code == 404

    fb = client.post("/media/1/feedback", json={"text": "  esse trecho é longo demais  ", "seg_start_s": 100})
    assert fb.status_code == 201 and fb.json()["interpreted"] is False
    assert client.post("/media/1/feedback", json={"text": "   "}).status_code == 422
    assert client.post("/media/99/feedback", json={"text": "x"}).status_code == 404


def test_api_aceita_proposta(settings: Settings, db: Session) -> None:
    _seed(db)
    client = TestClient(create_app(settings))
    out = client.post("/projects/1/learning/accept").json()
    assert out["applied"]["w_marker"] == out["weights"]["w_marker"] > defaults()["w_marker"]
    four = sum(out["applied"][k] for k in ("w_marker", "w_emotion", "w_speech", "w_novelty"))
    assert four == pytest.approx(1.0, abs=0.02)
