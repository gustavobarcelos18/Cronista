from __future__ import annotations

from pathlib import Path

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
