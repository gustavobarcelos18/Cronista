"""Fumaça da CLI: todo comando registrado responde a `--help` (a divisão em módulos não perde nenhum)."""

from __future__ import annotations

import typer.main
from typer.testing import CliRunner

from cronista.cli import app

runner = CliRunner()

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
