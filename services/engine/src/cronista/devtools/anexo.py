"""Anexo gerado da documentação: pacotes do engine, comandos da CLI e pastas do repositório (F14).

A árvore e a lista de comandos nunca são escritas à mão: este módulo as gera do código e do disco.
`python -m cronista.devtools.anexo` regrava `docs/anexo-gerado.md`; `--check` só compara (usado no
teste e no CI).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
ENGINE_PACKAGE = REPO_ROOT / "services" / "engine" / "src" / "cronista"
ANEXO = REPO_ROOT / "docs" / "anexo-gerado.md"

IGNORED = {
    "__pycache__",
    "node_modules",
    ".git",
    ".next",
    ".venv",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
}
# `docs/` fica de fora: listar os próprios documentos deixaria o anexo defasado a cada arquivo novo.
ROOT_DIRS = ("apps", "packages", "integrations", "profiles", "config", ".claude/skills")


def _first_line(text: str | None) -> str:
    return text.strip().splitlines()[0].strip() if text and text.strip() else ""


def _module_doc(path: Path) -> str:
    try:
        return _first_line(ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))))
    except (OSError, SyntaxError):
        return ""


def engine_packages() -> list[tuple[str, str]]:
    """Subpacotes e módulos soltos do pacote `cronista`, com a primeira linha da docstring."""
    rows: list[tuple[str, str]] = []
    for entry in sorted(ENGINE_PACKAGE.iterdir(), key=lambda p: p.name):
        if entry.name in IGNORED or entry.name == "__init__.py":
            continue
        if entry.is_dir() and (entry / "__init__.py").exists():
            rows.append((f"{entry.name}/", _module_doc(entry / "__init__.py")))
        elif entry.suffix == ".py":
            rows.append((entry.name, _module_doc(entry)))
    return rows


def cli_commands() -> list[tuple[str, str, str]]:
    """(nome, ajuda, observação) de cada comando registrado no `app` da CLI."""
    import typer.main

    from cronista.cli import app

    rows: list[tuple[str, str, str]] = []
    for name, command in sorted(typer.main.get_command(app).commands.items()):  # type: ignore[attr-defined]
        notes = []
        if command.deprecated:
            notes.append("deprecado")
        if command.hidden:
            notes.append("alias escondido")
        rows.append((name, _first_line(command.help) or _first_line(command.short_help), ", ".join(notes)))
    return rows


def repo_dirs() -> list[tuple[str, list[str]]]:
    rows: list[tuple[str, list[str]]] = []
    for name in ROOT_DIRS:
        base = REPO_ROOT / name
        if base.is_dir():
            kids = sorted(
                p.name + ("/" if p.is_dir() else "") for p in base.iterdir() if p.name not in IGNORED
            )
            rows.append((name, kids))
    return rows


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def render() -> str:
    out = [
        "# Anexo gerado: pacotes, comandos e pastas",
        "",
        "> **Gerado por `python -m cronista.devtools.anexo`; não edite à mão.** O teste",
        "> `test_anexo_gerado` falha se este arquivo ficar diferente do código. Fonte: docstrings dos",
        "> pacotes, o `app` Typer e as pastas do repositório.",
        "",
        "## Pacotes do engine (`services/engine/src/cronista/`)",
        "",
        "| Pacote ou módulo | O que é |",
        "|---|---|",
    ]
    out += [f"| `{n}` | {_cell(d)} |" for n, d in engine_packages()]
    out += [
        "",
        "## Comandos da CLI (`cronista --help`)",
        "",
        "| Comando | O que faz | Observação |",
        "|---|---|---|",
    ]
    out += [f"| `{n}` | {_cell(h)} | {o} |" for n, h, o in cli_commands()]
    out += ["", "## Pastas do repositório", ""]
    for name, kids in repo_dirs():
        out.append(f"- `{name}/`: " + (", ".join(f"`{k}`" for k in kids) if kids else "(vazia)"))
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        current = ANEXO.read_text(encoding="utf-8").replace("\r\n", "\n") if ANEXO.exists() else ""
        if current != text:
            print("docs/anexo-gerado.md desatualizado: rode `python -m cronista.devtools.anexo`")
            return 1
        return 0
    ANEXO.write_text(text, encoding="utf-8", newline="\n")
    print(f"gerado: {ANEXO}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
