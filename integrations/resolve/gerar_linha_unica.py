"""Junta cronista_kit_teste.lua numa linha só, para colar no Console do Resolve (que não tem dofile/io).

Uso: uv run integrations/resolve/gerar_linha_unica.py [saida]
Padrão: data/prod/kit-resolve/teste-linha-unica.lua. A saída precisa ficar dentro do repositório.
A pasta do kit vem da variável `KIT_DIR` (padrão: data/prod/kit-resolve no repositório).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]


def strip_comment(line: str) -> str:
    """Tira o comentário `--` do fim da linha, sem mexer em `--` que esteja dentro de uma string."""
    quote: str | None = None
    for i, char in enumerate(line):
        if quote:
            if char == quote and line[i - 1] != "\\":
                quote = None
        elif char in "\"'":
            quote = char
        elif line.startswith("--", i):
            return line[:i].rstrip()
    return line.rstrip()


def build(source: str, kit_dir: Path) -> str:
    lines = [ln.strip() for ln in source.splitlines() if ln.strip() and not ln.strip().startswith("--")]
    one_line = " ".join(strip_comment(ln) for ln in lines)
    return one_line.replace("__KIT_DIR__", str(kit_dir).replace("\\", "\\\\"))


if __name__ == "__main__":
    kit_dir = Path(os.environ.get("KIT_DIR") or REPO_ROOT / "data" / "prod" / "kit-resolve").resolve()
    requested = Path(sys.argv[1]) if len(sys.argv) > 1 else kit_dir / "teste-linha-unica.lua"
    target = (REPO_ROOT / requested).resolve()
    if not target.is_relative_to(REPO_ROOT):
        sys.exit(f"erro: a saída deve ficar dentro do repositório ({REPO_ROOT}): {target}")
    result = build((HERE / "cronista_kit_teste.lua").read_text(encoding="utf-8"), kit_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result, encoding="utf-8")
    print(f"{target}: {len(result)} caracteres")
