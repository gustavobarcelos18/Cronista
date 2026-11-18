from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cronista.api.app import create_app
from cronista.config import Settings
from cronista.db.models import Artifact, Marker, MediaFile, Project, RecordingSession
from cronista.domain.models import StageResult


def _seed(db: Session) -> None:
    project = Project(name="serie")
    session = RecordingSession(project=project, folder="pasta")
    media = MediaFile(session=session, path="C:/x/a.mp4", ordinal=0, size_bytes=10)
    db.add_all([project, session, media])
    db.flush()
    db.add(
        Marker(session_id=session.id, media_file_id=media.id, marker_id="1", kind="novo_dia", media_frame=60)
    )
    db.commit()


def test_api_le_sessoes_e_marcadores(settings: Settings, db: Session) -> None:
    _seed(db)
    client = TestClient(create_app(settings))
    assert client.get("/health").json()["status"] == "ok"
    sessions = client.get("/sessions").json()
    assert sessions[0]["project"] == "serie" and sessions[0]["files"][0]["name"] == "a.mp4"
    assert client.get("/sessions/1/markers").json()[0]["media_frame"] == 60
    assert client.get("/sessions/1/jobs").json() == []
    assert client.get("/sessions/99").status_code == 404


def test_api_segmentos_e_video(settings: Settings, db: Session, tmp_path: Path) -> None:
    _seed(db)
    client = TestClient(create_app(settings))
    assert client.get("/media/1/segments").json() == []
    assert client.get("/media/99/segments").status_code == 404
    assert client.get("/media/1/video").status_code == 404

    video = tmp_path / "m.mp4"
    video.write_bytes(b"0123456789")
    result = tmp_path / "normalize.json"
    result.write_text(StageResult(data={"media": str(video)}).model_dump_json())
    db.add(Artifact(media_file_id=1, stage="normalize", cache_key="k", result_path=str(result)))
    db.commit()
    resp = client.get("/media/1/video", headers={"Range": "bytes=2-4"})
    assert resp.status_code == 206 and resp.content == b"234"


def test_api_eventos_e_waveform(settings: Settings, db: Session, tmp_path: Path) -> None:
    import numpy as np

    from cronista.audio.events import replace_events
    from cronista.audio.signals import SIGNALS_KEY, write_signal
    from cronista.domain.evidence import AnalysisEvent, Evidence, EvidenceSource

    _seed(db)
    client = TestClient(create_app(settings))
    assert client.get("/media/99/events").status_code == 404
    assert client.get("/media/1/waveform").status_code == 404  # sem sinais ainda

    ev = Evidence(
        source=EvidenceSource.EVENTO,
        start_frame=120,
        end_frame=180,
        confidence=0.8,
        model="m",
        model_version="1",
        params_hash="h",
    )
    replace_events(db, 1, "speech", "", [AnalysisEvent(kind="speech", evidence=ev)])
    replace_events(db, 1, "relevance", "", [AnalysisEvent(kind="segment", evidence=ev)])
    events = client.get("/media/1/events").json()
    assert [(e["stage"], e["start_s"], e["end_s"]) for e in events] == [("speech", 2.0, 3.0)]

    meta = write_signal(
        tmp_path,
        "game.energy_db",
        np.linspace(-60, 0, 100),
        unit="dBFS",
        source_track="game",
        version="1",
        params={},
    )
    result = tmp_path / "signals.json"
    result.write_text(
        StageResult(data={SIGNALS_KEY: {"game.energy_db": meta.model_dump()}}).model_dump_json()
    )
    db.add(Artifact(media_file_id=1, stage="audio_signals", cache_key="k2", result_path=str(result)))
    db.commit()
    wave = client.get("/media/1/waveform?points=10").json()
    assert len(wave["game"]) == 10 and wave["mic"] == [] and wave["duration_s"] == 10.0
    assert wave["game"][-1] == 0.0


def test_api_decisoes_so_insercao(settings: Settings, db: Session) -> None:
    from cronista.audio.events import replace_events
    from cronista.db.models import SegmentDecision
    from cronista.relevance.engine import RelevanceParams, Segment
    from cronista.relevance.service import segments_to_events

    _seed(db)
    seg = Segment(10, 20, "momento", 0.8)
    replace_events(db, 1, "relevance", "", segments_to_events([seg], RelevanceParams()))
    client = TestClient(create_app(settings))
    assert client.get("/media/1/segments").json()[0]["decision"] is None
    assert client.post("/media/1/segments/99/decision", json={"decision": "aceito"}).status_code == 404
    url = "/media/1/segments/10/decision"
    assert client.post(url, json={"decision": "rejeitado"}).json()["decision"] == "rejeitado"
    assert client.post(url, json={"decision": "ajustado", "start_s": 5, "end_s": 4}).status_code == 422
    out = client.post(url, json={"decision": "ajustado", "start_s": 11, "end_s": 18}).json()
    assert (out["adj_start_s"], out["adj_end_s"]) == (11, 18)
    assert client.get("/media/1/segments").json()[0]["decision"] == "ajustado"
    rows = db.query(SegmentDecision).order_by(SegmentDecision.id).all()
    assert [r.decision for r in rows] == ["rejeitado", "ajustado"] and rows[1].replaces_id == rows[0].id


def test_segmentos_efetivos_aplicam_decisoes(db: Session) -> None:
    from cronista.audio.events import replace_events
    from cronista.relevance.engine import RelevanceParams, Segment
    from cronista.relevance.service import segments_to_events
    from cronista.review.decisions import load_effective_segments, record_decision

    _seed(db)
    segs = [Segment(10, 20, "momento", 0.8), Segment(30, 40, "momento", 0.7), Segment(50, 60, "momento", 0.6)]
    replace_events(db, 1, "relevance", "", segments_to_events(segs, RelevanceParams()))
    record_decision(db, 1, 10, "rejeitado")
    record_decision(db, 1, 30, "ajustado", 32.4, 38.6)
    record_decision(db, 1, 50, "aceito")
    out = load_effective_segments(db, 1)
    assert [(s.start_s, s.end_s) for s in out] == [(32, 39), (50, 60)]
    record_decision(db, 1, 10, "aceito")  # a última decisão vale
    assert [s.start_s for s in load_effective_segments(db, 1)] == [10, 32, 50]


def test_api_roteiro_edita_e_guarda_historico(settings: Settings) -> None:
    import json

    folder = settings.data_dir / "story" / "1"
    folder.mkdir(parents=True)
    pack = {
        "capitulos": [
            {
                "beats": [
                    {
                        "segmento_id": "s-1",
                        "inicio_s": 10,
                        "fim_s": 30,
                        "lacunas": [{"inicio_s": 10, "fim_s": 20}],
                    }
                ]
            }
        ]
    }
    client = TestClient(create_app(settings))
    assert client.get("/sessions/1/script").status_code == 404
    body = {"lines": [{"segment_id": "s-1", "text": "Aqui ele perdeu tudo."}]}
    assert client.put("/sessions/1/script", json=body).status_code == 422  # sem story-pack

    (folder / "story-pack.json").write_text(json.dumps(pack), encoding="utf-8")
    bad = client.put("/sessions/1/script", json={"lines": [{"segment_id": "zzz", "text": "x"}]})
    assert bad.status_code == 422 and "inexistente" in bad.json()["detail"]["errors"][0]
    assert not (folder / "roteiro.json").exists()  # erro não grava nada

    ok = client.put("/sessions/1/script", json=body).json()
    assert ok["script"]["lines"][0]["est_s"] > 0
    body["lines"][0]["text"] = "Aqui ele perdeu a casa inteira."
    client.put("/sessions/1/script", json=body)
    assert client.get("/sessions/1/script").json()["script"]["lines"][0]["text"].endswith("inteira.")
    assert "perdeu tudo" in (folder / "roteiro.v1.json").read_text(encoding="utf-8")
    assert (folder / "roteiro.srt").is_file()


def test_api_reexport_estados(settings: Settings, db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    import threading
    from types import SimpleNamespace

    from cronista.review import reexport

    _seed(db)
    gate, calls = threading.Event(), []

    def fake_export(
        _db: object, session_id: int, _s: object, script: object, target_s: float, *_a: object
    ) -> SimpleNamespace:
        calls.append((session_id, script, target_s))
        gate.wait(5)
        return SimpleNamespace(
            directory=Path("x"), version=2, reused=True, problems=[], warnings=["aviso"], clips=1
        )

    monkeypatch.setattr(reexport, "export_montagem", fake_export)
    monkeypatch.setattr(reexport, "build_gate", lambda _s: None)
    app = create_app(settings)
    client = TestClient(app)
    assert client.get("/sessions/1/export").json()["state"] == "idle"
    assert client.post("/sessions/99/export").status_code == 404
    assert client.post("/sessions/1/export?target_min=30").status_code == 202
    assert client.get("/sessions/1/export").json()["state"] == "running"
    assert client.post("/sessions/1/export").status_code == 409
    gate.set()
    app.state.reexport.last_thread.join(5)
    done = client.get("/sessions/1/export").json()
    assert (
        done["state"] == "done" and done["reused"] and done["version"] == 2 and done["warnings"] == ["aviso"]
    )
    assert calls == [(1, None, 1800.0)]

    def boom(*_a: object, **_k: object) -> None:
        raise ValueError("sem segmentos")

    monkeypatch.setattr(reexport, "export_montagem", boom)
    assert client.post("/sessions/1/export").status_code == 202
    app.state.reexport.last_thread.join(5)
    err = client.get("/sessions/1/export").json()
    assert err["state"] == "error" and "sem segmentos" in err["message"]


def test_api_progresso_sse(settings: Settings, db: Session) -> None:
    from cronista.db.models import Job

    _seed(db)
    db.add_all(
        [
            Job(media_file_id=1, stage="normalize", status="done"),
            Job(media_file_id=1, stage="audio", status="running"),
        ]
    )
    db.commit()
    client = TestClient(create_app(settings))
    snap = client.get("/sessions/1/progress").json()
    assert (snap["total"], snap["running"], snap["done"], snap["active"], snap["current"]) == (
        2,
        1,
        1,
        True,
        "audio",
    )

    db.query(Job).update({"status": "done"})
    db.commit()
    with client.stream("GET", "/sessions/1/progress/stream?interval_s=0.05") as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = "".join(resp.iter_text())
    assert "event: progress" in body and '"active":false' in body and body.rstrip().endswith("data: {}")


def test_api_painel_da_serie(settings: Settings, db: Session) -> None:
    from cronista.audio.events import replace_events
    from cronista.relevance.engine import RelevanceParams, Segment
    from cronista.relevance.service import segments_to_events
    from cronista.review.decisions import record_decision

    _seed(db)  # tem um marcador `novo_dia`
    segs = [Segment(0, 30, "conquista", 0.9), Segment(60, 90, "morte_falha", 0.8)]
    replace_events(db, 1, "relevance", "", segments_to_events(segs, RelevanceParams()))
    client = TestClient(create_app(settings))
    panel = client.get("/series").json()
    assert panel["total_min"] == 1.0 and panel["situacao"] == "faltando"
    assert panel["sessoes"][0]["dias"] == 1
    assert set(panel["por_classe_min"]) == {"conquista", "morte_falha"}

    record_decision(db, 1, 60, "rejeitado")  # rejeitar baixa a estimativa
    assert client.get("/series").json()["total_min"] == 0.5


def test_painel_avisa_capitulos_curtos_e_recalcula_apos_revisao(settings: Settings, db: Session) -> None:
    from cronista.audio.events import replace_events
    from cronista.relevance.engine import RelevanceParams, Segment
    from cronista.relevance.service import segments_to_events

    _seed(db)
    next_session = RecordingSession(project_id=1, folder="segunda")
    next_media = MediaFile(session=next_session, path="C:/x/b.mp4", ordinal=0)
    db.add(next_media)
    db.flush()
    db.add(
        Marker(
            session_id=next_session.id,
            media_file_id=next_media.id,
            marker_id="2",
            kind="novo_dia",
            media_frame=20 * 60,
        )
    )
    db.commit()
    replace_events(
        db,
        1,
        "relevance",
        "",
        segments_to_events([Segment(0, 16, "conquista", 0.9, markers=["1"])], RelevanceParams()),
    )
    replace_events(
        db,
        next_media.id,
        "relevance",
        "",
        segments_to_events(
            [Segment(0, 14, "conquista", 0.9), Segment(20, 30, "conquista", 0.9, markers=["2"])],
            RelevanceParams(),
        ),
    )
    client = TestClient(create_app(settings))
    chapter_2 = {"projeto_id": 1, "projeto": "serie", "capitulo": 2, "produto_s": 10.0}
    before = client.get("/series").json()
    assert before["referencia_capitulo_s"] == 30
    # O primeiro capítulo soma 16 + 14 s, atravessa duas sessões e já alcança a referência.
    assert before["capitulos_com_pouco_material"] == [chapter_2]

    decision = client.post(f"/media/{next_media.id}/segments/0/decision", json={"decision": "rejeitado"})
    assert decision.status_code == 200
    assert client.get("/series").json()["capitulos_com_pouco_material"] == [
        {**chapter_2, "capitulo": 1, "produto_s": 16.0},
        chapter_2,
    ]


def test_decisao_presa_a_janela_e_ajuste_validado(settings: Settings, db: Session) -> None:
    from cronista.audio.events import replace_events
    from cronista.relevance.engine import RelevanceParams, Segment
    from cronista.relevance.service import segments_to_events
    from cronista.review.decisions import load_effective_segments

    _seed(db)
    params = RelevanceParams()
    replace_events(
        db, 1, "relevance", "",
        segments_to_events([Segment(10, 20, "momento", 0.8), Segment(30, 40, "momento", 0.7)], params),
    )  # fmt: skip
    client = TestClient(create_app(settings))
    assert client.post("/media/1/segments/10/decision", json={"decision": "rejeitado"}).status_code == 200
    assert [s.start_s for s in load_effective_segments(db, 1)] == [30]

    # relevância recalculada: outro trecho no mesmo segundo, com outra janela; a rejeição não vale para ele
    replace_events(db, 1, "relevance", "", segments_to_events([Segment(10, 25, "momento", 0.6)], params))
    assert [s.start_s for s in load_effective_segments(db, 1)] == [10]
    assert client.get("/media/1/segments").json()[0]["decision"] is None

    replace_events(
        db, 1, "relevance", "",
        segments_to_events([Segment(10, 20, "momento", 0.8), Segment(30, 40, "momento", 0.7)], params),
    )  # fmt: skip
    over = client.post(
        "/media/1/segments/10/decision", json={"decision": "ajustado", "start_s": 12, "end_s": 35}
    )
    assert over.status_code == 422 and "invade" in over.json()["detail"]
    ok = client.post(
        "/media/1/segments/10/decision", json={"decision": "ajustado", "start_s": 12, "end_s": 28}
    )
    assert ok.status_code == 200


def test_api_recusa_escrita_de_origem_estranha(settings: Settings, db: Session) -> None:
    _seed(db)
    client = TestClient(create_app(settings))
    evil = {"Origin": "https://site-qualquer.example"}
    assert client.post("/sessions/1/export", headers=evil).status_code == 403
    assert client.post("/projects/1/learning/accept", headers=evil).status_code == 403
    assert client.get("/sessions", headers=evil).status_code == 200  # leitura segue regida pelo CORS
    studio = {"Origin": "http://localhost:3000"}
    assert client.post("/projects/1/learning/accept", headers=studio).status_code == 409  # passou do filtro


def test_salvar_roteiro_falha_sem_perder_o_atual(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from cronista.story import service
    from cronista.story.models import Script, ScriptLine

    folder = settings.data_dir / "story" / "1"
    folder.mkdir(parents=True)
    pack = {
        "capitulos": [
            {
                "beats": [
                    {
                        "segmento_id": "s-1",
                        "inicio_s": 1,
                        "fim_s": 30,
                        "lacunas": [{"inicio_s": 1, "fim_s": 20}],
                    }
                ]
            }
        ]
    }
    (folder / "story-pack.json").write_text(json.dumps(pack), encoding="utf-8")
    service.save_script(folder, Script(lines=[ScriptLine(segment_id="s-1", text="Primeira versão.")]))

    def boom(*_a: object, **_k: object) -> str:
        raise OSError("disco cheio")

    monkeypatch.setattr(service, "to_srt", boom)
    with pytest.raises(OSError):
        service.save_script(folder, Script(lines=[ScriptLine(segment_id="s-1", text="Segunda versão.")]))
    assert "Primeira" in (folder / "roteiro.json").read_text(encoding="utf-8")  # o atual ficou intacto
    assert not (folder / "roteiro.v1.json").exists()
