from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cronista.api.app import create_app
from cronista.config import Settings
from cronista.db.models import Project, RecordingSession
from cronista.packaging.panel import packaging_panel
from cronista.packaging.service import save_titles
from cronista.packaging.titles import TitleOption, TitleSet


@pytest.fixture
def session_id(db: Session) -> int:
    project = Project(name="serie")
    session = RecordingSession(project=project, folder="pasta")
    db.add_all([project, session])
    db.commit()
    return session.id


@pytest.fixture
def client(settings: Settings, session_id: int) -> TestClient:
    return TestClient(create_app(settings))


def packaging(settings: Settings, session_id: int) -> Path:
    return settings.data_dir / "packaging" / str(session_id)


def shorts_folder(settings: Settings, session_id: int) -> Path:
    return settings.data_dir / "shorts" / str(session_id)


def seed(settings: Settings, session_id: int, *, shorts: int = 3) -> None:
    """Títulos sugeridos, 2 variações de thumbnail e `shorts` Shorts renderizados."""
    folder = packaging(settings, session_id)
    titles = ["Derrotei o dragão", "A casa que caiu", "Do zero ao Nether"]
    save_titles(
        folder,
        TitleSet(
            provider="claude",
            titles=[TitleOption(text=t, reason="fato") for t in titles],
            thumbnail_texts=["Morri de novo"],
        ),
    )
    (folder / "thumbnails").mkdir(parents=True)
    entries = []
    for n, name in enumerate(["a.jpg", "b.jpg"], start=1):
        (folder / "thumbnails" / name).write_bytes(b"jpg" + bytes([n]))
        entries.append({"variacao": n, "arquivo": name, "texto": "MORRI", "posicao": "centro"})
    (folder / "thumbnails.json").write_text(json.dumps(entries), encoding="utf-8")
    sf = shorts_folder(settings, session_id)
    sf.mkdir(parents=True)
    rows = [
        {
            "file_id": 1,
            "start_frame": 600 * (i + 1),
            "end_frame": 600 * (i + 1) + 600,
            "score": 0.9 - i * 0.1,
            "reason": f"pico {i}",
            "duracao_s": 10.0,
        }
        for i in range(shorts)
    ]
    (sf / f"shorts-{session_id}.json").write_text(
        json.dumps({"fps": 60, "candidatos": rows}), encoding="utf-8"
    )
    for r in rows:
        (sf / f"short-1-{r['start_frame']}-{r['end_frame']}-h.mp4").write_bytes(b"0123456789")


def test_painel_vazio_lista_o_que_falta(client: TestClient, session_id: int) -> None:
    body = client.get(f"/sessions/{session_id}/packaging").json()
    assert body["title"]["suggestions"] == [] and body["thumbnails"] == [] and body["shorts"] == []
    assert body["ready"] is False and len(body["missing"]) == 3
    assert client.get("/sessions/99/packaging").status_code == 404


def test_painel_mostra_sugestoes_thumbnails_e_shorts(
    client: TestClient, settings: Settings, session_id: int
) -> None:
    seed(settings, session_id)
    body = client.get(f"/sessions/{session_id}/packaging").json()
    assert [s["text"] for s in body["title"]["suggestions"]] == [
        "Derrotei o dragão",
        "A casa que caiu",
        "Do zero ao Nether",
    ]
    assert body["title"]["thumbnail_texts"] == ["Morri de novo"] and body["title"]["chosen"] is None
    assert [t["variation"] for t in body["thumbnails"]] == [1, 2]
    assert [s["decision"] for s in body["shorts"]] == ["pendente"] * 3
    assert all(s["has_clip"] for s in body["shorts"]) and body["approved_shorts"] == 0


def test_escolhas_sao_insercoes_e_o_painel_chega_completo(
    client: TestClient, settings: Settings, session_id: int
) -> None:
    seed(settings, session_id)
    base = f"/sessions/{session_id}/packaging"
    title = client.post(f"{base}/title", json={"suggestion": 2}).json()["title"]
    assert (title["chosen"], title["origin"]) == ("A casa que caiu", "sugerido")
    edited = client.post(f"{base}/title", json={"suggestion": 2, "text": "A casa que caiu de novo"}).json()
    assert (edited["title"]["chosen"], edited["title"]["origin"]) == ("A casa que caiu de novo", "editado")
    own = client.post(f"{base}/title", json={"text": "Meu título"}).json()
    assert own["title"]["origin"] == "proprio"

    picked = client.post(f"{base}/thumbnail", json={"variation": 2}).json()
    assert [t["chosen"] for t in picked["thumbnails"]] == [False, True]

    keys = [s["key"] for s in picked["shorts"]]
    for key in keys:
        out = client.post(f"{base}/shorts/{key}/decision", json={"decision": "aprovado"}).json()
    assert out["approved_shorts"] == 3 and out["missing"] == [] and out["ready"] is True
    back = client.post(f"{base}/shorts/{keys[0]}/decision", json={"decision": "padrao"}).json()
    assert back["approved_shorts"] == 2 and back["shorts"][0]["decision"] == "pendente"
    assert back["missing"] == ["aprovar Shorts (2 de 3)"]


def test_erros_viram_422_ou_404(client: TestClient, settings: Settings, session_id: int) -> None:
    base = f"/sessions/{session_id}/packaging"
    assert client.post(f"{base}/title", json={}).status_code == 422  # nada informado
    assert client.post(f"{base}/title", json={"suggestion": 1}).status_code == 422  # sem sugestões salvas
    assert client.post(f"{base}/title", json={"text": "a" * 101}).status_code == 422
    assert client.post(f"{base}/thumbnail", json={"variation": 1}).status_code == 422  # sem thumbnails
    assert client.post(f"{base}/shorts/9-9/decision", json={"decision": "aprovado"}).status_code == 422
    assert client.post(f"{base}/shorts/9-9/decision", json={"decision": "talvez"}).status_code == 422
    assert client.post("/sessions/99/packaging/title", json={"text": "x"}).status_code == 404
    assert client.post("/sessions/99/packaging/publish").status_code == 404
    seed(settings, session_id)
    assert client.post(f"{base}/thumbnail", json={"variation": 7}).status_code == 422


def test_so_serve_arquivos_do_manifesto(client: TestClient, settings: Settings, session_id: int) -> None:
    base = f"/sessions/{session_id}/packaging"
    assert client.get(f"{base}/thumbnails/a.jpg").status_code == 404  # nada gerado ainda
    assert client.get(f"{base}/shorts/1-600-1200/video").status_code == 404
    seed(settings, session_id)
    ok = client.get(f"{base}/thumbnails/a.jpg")
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/jpeg"
    (packaging(settings, session_id) / "segredo.jpg").write_bytes(b"x")
    assert client.get(f"{base}/thumbnails/segredo.jpg").status_code == 404  # fora do manifesto
    assert client.get(f"{base}/thumbnails/..%2Fsegredo.jpg").status_code == 404
    video = client.get(f"{base}/shorts/1-600-1200/video", headers={"Range": "bytes=2-4"})
    assert video.status_code == 206 and video.content == b"234"
    assert client.get(f"{base}/shorts/1-999/video").status_code == 404


def test_publicar_monta_a_pasta_e_avisa_o_que_falta(
    client: TestClient, settings: Settings, session_id: int
) -> None:
    seed(settings, session_id)
    base = f"/sessions/{session_id}/packaging"
    client.post(f"{base}/title", json={"suggestion": 1})
    client.post(f"{base}/thumbnail", json={"variation": 1})
    for s in client.get(base).json()["shorts"]:
        client.post(f"{base}/shorts/{s['key']}/decision", json={"decision": "aprovado"})
    out = client.post(f"{base}/publish").json()
    assert out["files"].count("LEIA-ME.md") == 1 and "thumbnail.jpg" in out["files"]
    assert out["ready"] is False and any(
        "vídeo da série" in m for m in out["missing"]
    )  # o vídeo vem pela CLI
    folder = Path(out["directory"])
    assert (folder / "titulo.txt").read_text(encoding="utf-8") == "Derrotei o dragão\n"
    assert sorted(p.name for p in folder.glob("short-*.mp4")) == [
        "short-01.mp4",
        "short-02.mp4",
        "short-03.mp4",
    ]


def test_painel_direto_ignora_thumbnail_apagada(db: Session, settings: Settings, session_id: int) -> None:
    seed(settings, session_id)
    (packaging(settings, session_id) / "thumbnails" / "b.jpg").unlink()
    panel = packaging_panel(
        db, session_id, packaging(settings, session_id), shorts_folder(settings, session_id)
    )
    assert [t.file_name for t in panel.thumbnails] == ["a.jpg"]


def test_escrita_de_origem_estranha_e_barrada(client: TestClient, session_id: int) -> None:
    resp = client.post(
        f"/sessions/{session_id}/packaging/title",
        json={"text": "x"},
        headers={"Origin": "http://site-qualquer.example"},
    )
    assert resp.status_code == 403
