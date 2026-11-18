from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from cronista.cli import app
from cronista.config import Settings
from cronista.db.models import Project, RecordingSession
from cronista.packaging.publish import (
    MIN_SHORTS,
    PublishError,
    build_publish_package,
    current_short_decisions,
    list_shorts,
    record_short_decision,
)
from cronista.packaging.service import record_title_choice
from cronista.thumbnails.service import record_thumbnail_choice


@pytest.fixture
def session_id(db: Session) -> int:
    project = Project(name="serie")
    session = RecordingSession(project=project, folder="pasta")
    db.add_all([project, session])
    db.commit()
    return session.id


def candidate(file_id: int, start: int, score: float) -> dict[str, object]:
    return {
        "file_id": file_id,
        "start_frame": start,
        "end_frame": start + 600,
        "score": score,
        "reason": f"pico {start}",
        "duracao_s": 10.0,
    }


def make_shorts(folder: Path, session_id: int, n: int = 4, *, render: bool = True) -> list[str]:
    """`n` candidatos no manifesto e, se `render`, um MP4 para cada um."""
    folder.mkdir(parents=True, exist_ok=True)
    rows = [candidate(1, 600 * (i + 1), 0.9 - i * 0.1) for i in range(n)]
    (folder / f"shorts-{session_id}.json").write_text(
        json.dumps({"fps": 60, "candidatos": rows}), encoding="utf-8"
    )
    if render:
        for r in rows:
            (folder / f"short-1-{r['start_frame']}-{r['end_frame']}-abc123.mp4").write_bytes(b"mp4")
    return [f"1-{r['start_frame']}" for r in rows]


def make_thumbnails(folder: Path, names: list[str]) -> None:
    (folder / "thumbnails").mkdir(parents=True, exist_ok=True)
    entries = []
    for n, name in enumerate(names, start=1):
        (folder / "thumbnails" / name).write_bytes(b"jpg")
        entries.append({"variacao": n, "arquivo": name, "texto": "MORRI DE NOVO", "posicao": "centro"})
    (folder / "thumbnails.json").write_text(json.dumps(entries), encoding="utf-8")


# ---------------------------------------------------------------- decisões (só inserção)


def test_listagem_acha_o_mp4_mais_recente_de_cada_candidato(session_id: int, tmp_path: Path) -> None:
    keys = make_shorts(tmp_path, session_id, 2)
    old = tmp_path / "short-1-600-1200-velho.mp4"
    old.write_bytes(b"velho")
    os.utime(old, (1, 1))  # mais antigo que o abc123
    entries = list_shorts(tmp_path, session_id)
    assert [e.key for e in entries] == keys
    assert entries[0].clip is not None and entries[0].clip.name == "short-1-600-1200-abc123.mp4"
    assert entries[0].reason == "pico 600" and entries[0].duration_s == 10.0


def test_candidato_sem_render_aparece_sem_mp4(session_id: int, tmp_path: Path) -> None:
    make_shorts(tmp_path, session_id, 1, render=False)
    assert list_shorts(tmp_path, session_id)[0].clip is None


def test_sem_manifesto_pede_o_render(session_id: int, tmp_path: Path) -> None:
    with pytest.raises(PublishError, match="shorts-render"):
        list_shorts(tmp_path, session_id)


def test_ultima_decisao_vale_e_padrao_volta_a_pendente(db: Session, session_id: int, tmp_path: Path) -> None:
    a, b, *_ = make_shorts(tmp_path, session_id)
    first = record_short_decision(db, session_id, tmp_path, a, "aprovado")
    record_short_decision(db, session_id, tmp_path, b, "rejeitado")
    assert current_short_decisions(db, session_id) == {a: "aprovado", b: "rejeitado"}
    record_short_decision(db, session_id, tmp_path, a, "rejeitado")
    assert current_short_decisions(db, session_id)[a] == "rejeitado"
    record_short_decision(db, session_id, tmp_path, a, "padrao")
    assert a not in current_short_decisions(db, session_id)  # pendente de novo
    assert first.id is not None  # a decisão anterior continua no banco (só inserção)


def test_decisao_recusa_o_que_nao_existe(db: Session, session_id: int, tmp_path: Path) -> None:
    keys = make_shorts(tmp_path, session_id, 1, render=False)
    with pytest.raises(PublishError, match="não existe"):
        record_short_decision(db, 999, tmp_path, keys[0], "aprovado")
    with pytest.raises(PublishError, match="inválida"):
        record_short_decision(db, session_id, tmp_path, keys[0], "talvez")
    with pytest.raises(PublishError, match="Short '9-9'"):
        record_short_decision(db, session_id, tmp_path, "9-9", "aprovado")
    with pytest.raises(PublishError, match="não foi renderizado"):
        record_short_decision(db, session_id, tmp_path, keys[0], "aprovado")
    assert record_short_decision(db, session_id, tmp_path, keys[0], "rejeitado").decision == "rejeitado"


# ---------------------------------------------------------------- pasta de publicação


def complete_setup(db: Session, session_id: int, tmp_path: Path) -> tuple[Path, Path, list[str]]:
    shorts, pack = tmp_path / "shorts", tmp_path / "pack"
    keys = make_shorts(shorts, session_id, 5)
    make_thumbnails(pack, ["a.jpg", "b.jpg"])
    record_thumbnail_choice(db, session_id, pack, 2)
    record_title_choice(db, session_id, pack, text="Derrotei o dragão")
    for key in keys[:3]:
        record_short_decision(db, session_id, shorts, key, "aprovado")
    record_short_decision(db, session_id, shorts, keys[3], "rejeitado")  # o quinto fica pendente
    return shorts, pack, keys


def test_pacote_completo_tem_tudo_e_o_leia_me(db: Session, session_id: int, tmp_path: Path) -> None:
    shorts, pack, _ = complete_setup(db, session_id, tmp_path)
    video = tmp_path / "serie-final.mp4"
    video.write_bytes(b"video")
    report = build_publish_package(db, session_id, shorts, pack, video=video)
    assert report.ready and report.missing == []
    assert sorted(report.files) == sorted(
        [
            "serie-final.mp4",
            "titulo.txt",
            "thumbnail.jpg",
            "short-01.mp4",
            "short-02.mp4",
            "short-03.mp4",
            "LEIA-ME.md",
        ]
    )
    folder = pack / "publicacao"
    assert (folder / "titulo.txt").read_text(encoding="utf-8") == "Derrotei o dragão\n"
    assert (folder / "thumbnail.jpg").read_bytes() == b"jpg"
    readme = (folder / "LEIA-ME.md").read_text(encoding="utf-8")
    assert "Derrotei o dragão" in readme and "MORRI DE NOVO" in readme and "serie-final.mp4" in readme
    assert "Shorts aprovados: 3" in readme and "1 pendente(s), 1 rejeitado(s)" in readme
    assert "Nada: o pacote está completo." in readme


def test_pacote_so_leva_os_aprovados_na_ordem(db: Session, session_id: int, tmp_path: Path) -> None:
    shorts, pack, keys = complete_setup(db, session_id, tmp_path)
    record_short_decision(db, session_id, shorts, keys[0], "rejeitado")  # o melhor sai
    record_short_decision(db, session_id, shorts, keys[4], "aprovado")
    report = build_publish_package(db, session_id, shorts, pack)
    readme = (pack / "publicacao" / "LEIA-ME.md").read_text(encoding="utf-8")
    assert [n for n in report.files if n.startswith("short-")] == [
        "short-01.mp4",
        "short-02.mp4",
        "short-03.mp4",
    ]
    assert "pico 1200" in readme and "pico 3000" in readme and "pico 600" not in readme


def test_o_que_falta_vira_aviso_e_item_do_leia_me(db: Session, session_id: int, tmp_path: Path) -> None:
    shorts = tmp_path / "shorts"
    keys = make_shorts(shorts, session_id, 3)
    record_short_decision(db, session_id, shorts, keys[0], "aprovado")
    report = build_publish_package(db, session_id, shorts, tmp_path / "pack")
    assert not report.ready
    text = "\n".join(report.missing)
    assert "vídeo da série" in text and "título" in text and "thumbnail" in text
    assert f"1 aprovado(s), o plano pede pelo menos {MIN_SHORTS}" in text
    readme = (tmp_path / "pack" / "publicacao" / "LEIA-ME.md").read_text(encoding="utf-8")
    assert "**ainda não escolhida**" in readme and "ainda não incluído" in readme


def test_sem_shorts_renderizados_o_pacote_sai_sem_eles(db: Session, session_id: int, tmp_path: Path) -> None:
    report = build_publish_package(db, session_id, tmp_path / "nada", tmp_path / "pack")
    assert any("Shorts: 0 aprovado" in m for m in report.missing)


def test_refazer_troca_os_arquivos_e_mantem_o_video(db: Session, session_id: int, tmp_path: Path) -> None:
    shorts, pack, keys = complete_setup(db, session_id, tmp_path)
    video = tmp_path / "serie-final.mp4"
    video.write_bytes(b"video")
    build_publish_package(db, session_id, shorts, pack, video=video)
    record_short_decision(db, session_id, shorts, keys[2], "rejeitado")  # sobram 2 aprovados
    record_title_choice(db, session_id, pack, text="Outro título")
    report = build_publish_package(db, session_id, shorts, pack)  # sem --video: mantém o da vez anterior
    folder = pack / "publicacao"
    assert not (folder / "short-03.mp4").exists()
    assert (folder / "titulo.txt").read_text(encoding="utf-8") == "Outro título\n"
    assert "serie-final.mp4" in report.files and (folder / "serie-final.mp4").is_file()
    assert not list(folder.glob("part-*"))


def test_sem_video_o_pacote_usa_o_corte_mais_recente(db: Session, session_id: int, tmp_path: Path) -> None:
    shorts, pack, _ = complete_setup(db, session_id, tmp_path)
    old, new = tmp_path / "serie-v1.mp4", tmp_path / "serie-v2.mp4"
    old.write_bytes(b"1")
    build_publish_package(db, session_id, shorts, pack, video=old)
    new.write_bytes(b"2")
    build_publish_package(db, session_id, shorts, pack, video=new)
    assert not (pack / "publicacao" / "serie-v1.mp4").exists()  # D5: o vídeo anterior sai da pasta
    report = build_publish_package(db, session_id, shorts, pack)  # sem --video, como o botão do Studio
    assert "serie-v2.mp4" in report.files and "serie-v1.mp4" not in report.files


def test_pacote_recusa_pasta_com_arquivos_de_fora(db: Session, session_id: int, tmp_path: Path) -> None:
    shorts, pack, _ = complete_setup(db, session_id, tmp_path)
    other = tmp_path / "meus-arquivos"
    other.mkdir()
    (other / "short-01.mp4").write_bytes(b"meu")
    with pytest.raises(PublishError, match="não são de um pacote"):
        build_publish_package(db, session_id, shorts, pack, out=other)
    assert (other / "short-01.mp4").read_bytes() == b"meu"


def test_thumbnail_escolhida_que_saiu_do_manifesto_vira_falta(
    db: Session, session_id: int, tmp_path: Path
) -> None:
    shorts, pack, _ = complete_setup(db, session_id, tmp_path)
    make_thumbnails(pack, ["c.jpg", "d.jpg"])  # nova geração: o manifesto não lista mais a escolha (b.jpg)
    report = build_publish_package(db, session_id, shorts, pack)
    assert any(m.startswith("thumbnail:") for m in report.missing)
    assert not (pack / "publicacao" / "thumbnail.jpg").exists()


def test_pacote_recusa_sessao_e_video_inexistentes(db: Session, session_id: int, tmp_path: Path) -> None:
    with pytest.raises(PublishError, match="sessão 999"):
        build_publish_package(db, 999, tmp_path, tmp_path)
    with pytest.raises(PublishError, match="vídeo"):
        build_publish_package(db, session_id, tmp_path, tmp_path, video=tmp_path / "nao.mp4")


def test_thumbnail_apagada_depois_da_escolha_vira_falta(db: Session, session_id: int, tmp_path: Path) -> None:
    shorts, pack, _ = complete_setup(db, session_id, tmp_path)
    (pack / "thumbnails" / "b.jpg").unlink()
    report = build_publish_package(db, session_id, shorts, pack)
    assert any("b.jpg não existe mais" in m for m in report.missing)


# ---------------------------------------------------------------- CLI


def test_cli_fluxo_status_decidir_e_pacote(
    settings: Settings, db: Session, session_id: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CRONISTA_ENV", "test")
    monkeypatch.setattr("cronista.cli.load_settings", lambda: settings)
    keys = make_shorts(settings.data_dir / "shorts" / str(session_id), session_id, 3)
    runner = CliRunner()
    status = runner.invoke(app, ["shorts-status", str(session_id)])
    assert status.exit_code == 0 and "pendente" in status.output and keys[0] in status.output
    ok = runner.invoke(app, ["short-decidir", str(session_id), keys[0]])
    assert ok.exit_code == 0 and f"{keys[0]}: aprovado" in ok.output
    bad = runner.invoke(app, ["short-decidir", str(session_id), "9-9"])
    assert bad.exit_code == 1
    pkg = runner.invoke(app, ["pacote-publicacao", str(session_id)])
    assert pkg.exit_code == 2 and "falta: título" in pkg.output  # incompleto: sai com 2 e lista o que falta
    assert (settings.data_dir / "packaging" / str(session_id) / "publicacao" / "LEIA-ME.md").is_file()
