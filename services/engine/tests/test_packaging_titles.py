from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from cronista.config import Settings
from cronista.db.models import Project, RecordingSession
from cronista.packaging.service import (
    TitleError,
    current_title,
    record_title_choice,
    save_titles,
    title_history,
    write_title_pack,
)
from cronista.packaging.titles import (
    MAX_TITLE_CHARS,
    NullTitleProvider,
    TitleOption,
    TitleSet,
    build_title_pack,
    check_creator_thumbnail_text,
    check_creator_title,
    cliche_flags,
    load_titles,
    validate_titles,
)


def beat(seg: str, name: str, score: float, **extra: Any) -> dict[str, Any]:
    return {
        "segmento_id": seg,
        "arquivo_id": 1,
        "inicio_s": 0,
        "fim_s": 30,
        "beat": name,
        "classe": "acao",
        "nota": score,
        "razoes": ["morte do chefe", "emoção alta", "x" * 100, "quarta razão"],
        "marcadores": [],
        "fala_ao_vivo": [{"inicio_s": 1.0, "fim_s": 2.0, "texto": "consegui " * 40}],
        "lacunas": [],
        **extra,
    }


def story_pack() -> dict[str, Any]:
    return {
        "projeto": {"nome": "serie", "jogo": "Minecraft"},
        "alvo_s": 2400.0,
        "objetivos": [
            {
                "id": 2,
                "titulo": "Construir a casa",
                "tipo": "secundario",
                "estado": "concluido",
                "confirmado": True,
            },
            {
                "id": 1,
                "titulo": "Derrotar o dragão",
                "tipo": "principal",
                "estado": "falhou",
                "confirmado": True,
            },
            {"id": 3, "titulo": "Hipótese", "tipo": "principal", "estado": "proposto", "confirmado": False},
        ],
        "capitulos": [
            {"n": 1, "alocado_s": 600, "beats": [beat("1:0", "setup", 0.4), beat("1:60", "conflito", 0.9)]},
            {"n": 2, "alocado_s": 600, "beats": [beat("1:120", "falha", 0.7), beat("1:180", "falha", 0.9)]},
        ],
    }


def titles(*texts: str) -> TitleSet:
    return TitleSet(provider="claude", titles=[TitleOption(text=t, reason="fato") for t in texts])


# ---------------------------------------------------------------- pacote de entrada


def test_title_pack_is_compact_deterministic_and_has_no_day_number() -> None:
    pack = build_title_pack(story_pack())
    assert pack == build_title_pack(json.loads(json.dumps(story_pack())))
    assert [o["titulo"] for o in pack["objetivos"]] == [
        "Derrotar o dragão",
        "Construir a casa",
    ]  # principal primeiro, só confirmados
    assert pack["abertura"]["segmento_id"] == "1:0" and pack["desfecho"]["segmento_id"] == "1:180"
    assert [m["segmento_id"] for m in pack["momentos"][:2]] == ["1:180", "1:60"]  # maior nota, empate pelo id
    assert pack["arco"] == [
        {"capitulo": 1, "beats": {"setup": 1, "conflito": 1}, "desfecho": "conflito"},
        {"capitulo": 2, "beats": {"falha": 2}, "desfecho": "falha"},
    ]
    assert pack["limite_caracteres"] == MAX_TITLE_CHARS
    moment = pack["momentos"][0]
    assert len(moment["razoes"]) == 3 and all(len(r) <= 60 for r in moment["razoes"])
    assert len(moment["fala"]) <= 90
    assert "day" not in json.dumps(pack).lower() and len(json.dumps(pack, ensure_ascii=False)) < 6000


def test_title_pack_limits_moments_and_handles_an_empty_story() -> None:
    assert len(build_title_pack(story_pack(), top=2)["momentos"]) == 2
    empty = build_title_pack({"capitulos": []})
    assert empty["abertura"] is None and empty["desfecho"] is None and empty["momentos"] == []


# ---------------------------------------------------------------- validação


def test_valid_titles_pass_and_text_is_normalized() -> None:
    report = validate_titles(
        titles("Derrotei o dragão  depois de 12 tentativas", "A casa que quase caiu", "Do zero ao Nether")
    )
    assert report.ok and not report.warnings
    assert report.titles[0].text == "Derrotei o dragão depois de 12 tentativas"


@pytest.mark.parametrize(
    ("text", "flag"),
    [
        ("Você não vai acreditar no que aconteceu", "nao_vai_acreditar"),
        ("Isso mudou tudo no meu mundo", "mudou_tudo"),
        ("Um final CHOCANTE", "adjetivo_isca"),
        ("DERROTEI O DRAGÃO sozinho", "caixa_alta"),
        ("Consegui!!", "pontuacao_exagerada"),
        ("O que aconteceu depois", "suspense_vazio"),
    ],
)
def test_cliches_are_refused(text: str, flag: str) -> None:
    assert flag in cliche_flags(text)
    report = validate_titles(titles(text, "B título", "C título"))
    assert not report.ok and any("clichê" in e for e in report.errors)


def test_plain_title_with_a_single_capitalized_word_is_not_shouting() -> None:
    assert cliche_flags("Derrotei o Dragão no Nether") == []
    assert cliche_flags("Minha jornada com TNT") == []  # uma sigla sozinha não é grito


def test_length_empty_duplicates_and_count_limits() -> None:
    long = "a" * (MAX_TITLE_CHARS + 1)
    report = validate_titles(titles(long, "Repetido", "repetido", "Ok um", "Ok dois", "Ok três"))
    assert any("71 caracteres" in e for e in report.errors)
    assert any("repetido" in e for e in report.errors)
    assert any("máximo 5" in e for e in report.errors)
    assert validate_titles(titles("a" * MAX_TITLE_CHARS, "b", "c")).ok
    blank = validate_titles(TitleSet(titles=[TitleOption(text="   ")]))
    assert any("vazio" in e for e in blank.errors)


def test_few_titles_and_missing_reason_are_only_warnings() -> None:
    report = validate_titles(TitleSet(titles=[TitleOption(text="Um título só")]))
    assert report.ok
    assert any("só 1 título" in w for w in report.warnings) and any("`reason`" in w for w in report.warnings)


def test_ai_text_signals_are_warnings_not_errors() -> None:
    report = validate_titles(titles("Uma jornada épica no Nether", "B título", "C título"))
    assert report.ok and any("vocabulario_inflado" in w for w in report.warnings)


def test_creator_title_only_hits_the_hard_youtube_limit() -> None:
    assert check_creator_title("  Meu   título INCRÍVEL!!  ") == "Meu título INCRÍVEL!!"
    assert len(check_creator_title("a" * 100)) == 100
    for bad in ("", "   ", "a" * 101):
        with pytest.raises(ValueError, match="título"):
            check_creator_title(bad)


def test_null_provider_writes_nothing_and_load_rejects_garbage(tmp_path: Path) -> None:
    assert NullTitleProvider().write(build_title_pack(story_pack())).titles == []
    bad = tmp_path / "bad.json"
    bad.write_text("{nao é json", encoding="utf-8")
    with pytest.raises(ValueError, match="títulos inválidos"):
        load_titles(bad)
    with pytest.raises(ValueError, match="títulos inválidos"):
        load_titles(tmp_path / "ausente.json")


# ---------------------------------------------------------------- disco


def test_write_title_pack_needs_the_story_pack(tmp_path: Path) -> None:
    with pytest.raises(TitleError, match="cronista story"):
        write_title_pack(tmp_path / "story", tmp_path / "pack")
    (tmp_path / "story").mkdir()
    (tmp_path / "story" / "story-pack.json").write_text(json.dumps(story_pack()), encoding="utf-8")
    path = write_title_pack(tmp_path / "story", tmp_path / "pack")
    assert json.loads(path.read_text(encoding="utf-8"))["abertura"]["segmento_id"] == "1:0"


def test_save_titles_keeps_every_previous_version(tmp_path: Path) -> None:
    save_titles(tmp_path, titles("Primeiro", "Segundo", "Terceiro"))
    save_titles(tmp_path, titles("Quarto", "Quinto", "Sexto"))
    save_titles(tmp_path, titles("Sétimo", "Oitavo", "Nono"))
    assert load_titles(tmp_path / "titulos.json").titles[0].text == "Sétimo"
    assert load_titles(tmp_path / "titulos.v1.json").titles[0].text == "Primeiro"
    assert load_titles(tmp_path / "titulos.v2.json").titles[0].text == "Quarto"
    assert not list(tmp_path.glob("*.tmp"))


def test_save_titles_refuses_invalid_or_empty_and_keeps_the_current_file(tmp_path: Path) -> None:
    save_titles(tmp_path, titles("Bom um", "Bom dois", "Bom três"))
    with pytest.raises(TitleError) as bad:
        save_titles(tmp_path, titles("Você não vai acreditar", "B título", "C título"))
    assert any("clichê" in e for e in bad.value.errors)
    with pytest.raises(TitleError, match="nenhum título"):
        save_titles(tmp_path, NullTitleProvider().write({}))
    assert load_titles(tmp_path / "titulos.json").titles[0].text == "Bom um"
    assert not (tmp_path / "titulos.v1.json").exists()


# ---------------------------------------------------------------- escolha do criador (só inserção)


@pytest.fixture
def session_id(db: Session) -> int:
    project = Project(name="serie")
    session = RecordingSession(project=project, folder="pasta")
    db.add_all([project, session])
    db.commit()
    return session.id


def test_choice_origins_and_latest_wins(db: Session, session_id: int, tmp_path: Path) -> None:
    save_titles(tmp_path, titles("Derrotei o dragão", "A casa que caiu", "Do zero ao Nether"))
    assert current_title(db, session_id) is None

    first = record_title_choice(db, session_id, tmp_path, suggestion=2)
    assert (first.origin, first.text, first.suggested, first.provider) == (
        "sugerido",
        "A casa que caiu",
        "A casa que caiu",
        "claude",
    )
    edited = record_title_choice(
        db, session_id, tmp_path, suggestion=1, text="Derrotei o dragão (finalmente)"
    )
    assert (edited.origin, edited.suggested) == ("editado", "Derrotei o dragão")
    same = record_title_choice(db, session_id, tmp_path, suggestion=1, text="  Derrotei o dragão ")
    assert same.origin == "sugerido"
    own = record_title_choice(db, session_id, tmp_path, text="Meu título INCRÍVEL!!")
    assert (own.origin, own.suggested, own.provider) == ("proprio", None, None)

    current = current_title(db, session_id)
    assert current is not None and current.text == "Meu título INCRÍVEL!!"
    assert [h.origin for h in title_history(db, session_id)] == [
        "sugerido",
        "editado",
        "sugerido",
        "proprio",
    ]  # nada é apagado


def test_choice_errors(db: Session, session_id: int, tmp_path: Path) -> None:
    with pytest.raises(TitleError, match="não existe"):
        record_title_choice(db, 999, tmp_path, text="x")
    with pytest.raises(TitleError, match="informe"):
        record_title_choice(db, session_id, tmp_path)
    with pytest.raises(TitleError, match="titulos-import"):
        record_title_choice(db, session_id, tmp_path, suggestion=1)
    save_titles(tmp_path, titles("Um", "Dois", "Três"))
    for n in (0, 4):
        with pytest.raises(TitleError, match="não existe"):
            record_title_choice(db, session_id, tmp_path, suggestion=n)
    with pytest.raises(TitleError, match="101 caracteres"):
        record_title_choice(db, session_id, tmp_path, text="a" * 101)
    assert current_title(db, session_id) is None  # nada foi gravado


# ---------------------------------------------------------------- CLI


def test_cli_flow_pack_import_choose(
    settings: Settings, db: Session, session_id: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cronista import cli

    monkeypatch.setattr("cronista.commands.common.load_settings", lambda: settings)
    runner = CliRunner()
    story_dir = settings.data_dir / "story" / str(session_id)
    story_dir.mkdir(parents=True)
    (story_dir / "story-pack.json").write_text(json.dumps(story_pack()), encoding="utf-8")

    out = runner.invoke(cli.app, ["titulos", str(session_id)])
    assert out.exit_code == 0 and "/titular" in out.output
    assert (settings.data_dir / "packaging" / str(session_id) / "titulo-pack.json").is_file()

    file = tmp_path / "titulos.json"
    file.write_text(
        titles("Derrotei o dragão", "A casa que caiu", "Do zero ao Nether").model_dump_json(),
        encoding="utf-8",
    )
    out = runner.invoke(cli.app, ["titulos-import", str(session_id), str(file)])
    assert out.exit_code == 0 and "1. Derrotei o dragão (17)" in out.output

    file.write_text(titles("Chocante demais", "B título", "C título").model_dump_json(), encoding="utf-8")
    out = runner.invoke(cli.app, ["titulos-import", str(session_id), str(file)])
    assert out.exit_code == 1 and "clichê" in out.output

    out = runner.invoke(cli.app, ["titulos-escolher", str(session_id), "--sugestao", "2"])
    assert out.exit_code == 0 and "sugerido: A casa que caiu" in out.output
    out = runner.invoke(cli.app, ["titulos-escolher", str(session_id)])
    assert out.exit_code == 1 and "informe" in out.output
    out = runner.invoke(cli.app, ["titulos", "999"])
    assert out.exit_code == 1 and "cronista story" in out.output


# ---------------------------------------------------------------- textos de thumbnail (9B)


def with_thumbs(*texts: str) -> TitleSet:
    base = titles("Derrotei o dragão", "A casa que caiu", "Do zero ao Nether")
    return base.model_copy(update={"thumbnail_texts": list(texts)})


def test_textos_de_thumbnail_validos_sao_normalizados_e_guardados(tmp_path: Path) -> None:
    report = validate_titles(with_thumbs("  morri   de novo ", "O FIM"))
    assert report.ok and report.thumbnail_texts == ["morri de novo", "O FIM"]
    save_titles(tmp_path, with_thumbs("  morri   de novo "))
    assert load_titles(tmp_path / "titulos.json").thumbnail_texts == ["morri de novo"]


@pytest.mark.parametrize(
    "text",
    ["", "Morri", "um dois três quatro cinco", "a" * 20 + " " + "b" * 20, "VOCÊ NÃO VAI ACREDITAR"],
)
def test_texto_de_thumbnail_invalido_e_erro_e_nada_e_gravado(text: str, tmp_path: Path) -> None:
    assert not validate_titles(with_thumbs(text)).ok
    with pytest.raises(TitleError):
        save_titles(tmp_path, with_thumbs(text))
    assert not (tmp_path / "titulos.json").exists()


def test_texto_de_thumbnail_repetido_e_recusado() -> None:
    report = validate_titles(with_thumbs("Morri de novo", "morri DE novo"))
    assert any("repetido" in e for e in report.errors)


def test_texto_da_thumbnail_do_criador_so_esbarra_no_que_nao_cabe() -> None:
    assert check_creator_thumbnail_text("  Meu   texto INCRÍVEL!! ") == "Meu texto INCRÍVEL!!"
    with pytest.raises(ValueError, match="vazio"):
        check_creator_thumbnail_text("  ")
    with pytest.raises(ValueError, match="palavras"):
        check_creator_thumbnail_text("um dois três quatro cinco")
    assert check_creator_thumbnail_text("um dois três quatro cinco", 6)


def test_titulos_corrompidos_viram_erro_claro_e_nao_excecao(db: Session, tmp_path: Path) -> None:
    from cronista.packaging.panel import packaging_panel
    from cronista.packaging.service import TITLES_NAME, TitleError, record_title_choice

    project = Project(name="serie")
    session = RecordingSession(project=project, folder="pasta")
    db.add_all([project, session])
    db.commit()
    (tmp_path / TITLES_NAME).write_text("{não é json", encoding="utf-8")
    with pytest.raises(TitleError, match="titulos-import"):
        record_title_choice(db, session.id, tmp_path, suggestion=1)
    assert packaging_panel(db, session.id, tmp_path, tmp_path).title.suggestions == []


def test_nomes_antigos_dos_comandos_continuam_funcionando() -> None:
    """D9: convenção `<objeto-plural>-<verbo>`, com os nomes antigos como alias (escondidos e deprecados)."""
    from cronista import cli

    runner = CliRunner()
    for old, new in (
        ("titulo-escolher", "titulos-escolher"),
        ("thumbnail-escolher", "thumbnails-escolher"),
        ("short-decidir", "shorts-decidir"),
    ):
        assert runner.invoke(cli.app, [old, "--help"]).exit_code == 0
        assert runner.invoke(cli.app, [new, "--help"]).exit_code == 0
