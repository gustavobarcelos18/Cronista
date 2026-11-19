"""Fumaça da CLI: todo comando registrado responde a `--help` (a divisão em módulos não perde nenhum)."""

from __future__ import annotations

import pytest
import typer.main
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from cronista.cli import app
from cronista.commands.common import _pick_media
from cronista.db.models import MediaFile, Project, RecordingSession

runner = CliRunner()


def test_filtro_de_arquivo_ambiguo_exige_nome_especifico(db: Session) -> None:
    session = RecordingSession(project=Project(name="série"), folder="pasta")
    media = [
        MediaFile(session=session, path=name, ordinal=n)
        for n, name in enumerate(("dia.mp4", "outro-dia.mp4"))
    ]
    db.add_all(media)
    db.commit()
    assert _pick_media(db, session.id, None) == media[0]
    assert _pick_media(db, session.id, "dia.mp4") == media[0]
    with pytest.raises(typer.BadParameter, match="mais de um arquivo"):
        _pick_media(db, session.id, "dia")


def test_alvo_invalido_e_recusado_antes_de_abrir_a_sessao() -> None:
    for command in ("story", "montar", "mixar", "montagem", "acabamento"):
        result = runner.invoke(app, [command, "1", "--target-min", "0"])
        assert result.exit_code == 2 and "240 minutos" in result.output, command


# Nomes públicos que o criador usa; a lista só cresce (um comando renomeado ganha alias deprecado).
EXPECTED = {
    "ingest", "status", "analyze", "report", "preview", "serve", "record", "relevance", "series", "story",
    "revisao", "roteiro-import", "roteiro-lint", "montar", "mixar", "montagem", "acabamento", "brand-check",
    "titulos", "titulos-import", "titulos-escolher", "thumbnails", "thumbnails-escolher", "shorts",
    "shorts-render", "shorts-status", "shorts-decidir", "pacote-publicacao", "gabarito", "resolve-kit",
    "fixtures", "api", "export",
}  # fmt: skip


def test_every_command_is_registered_and_answers_help() -> None:
    commands = typer.main.get_command(app).commands  # type: ignore[attr-defined]
    assert set(commands) >= EXPECTED
    for name in commands:
        result = runner.invoke(app, [name, "--help"])
        assert result.exit_code == 0, f"{name}: {result.output}"
