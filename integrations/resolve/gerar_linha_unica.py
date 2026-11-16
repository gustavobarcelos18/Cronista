"""Junta cronista_kit_teste.lua numa linha só, para colar no Console do Resolve (que não tem dofile/io).

Uso: uv run integrations/resolve/gerar_linha_unica.py [saida]
Padrão: data/prod/kit-resolve/teste-linha-unica.lua. A saída precisa ficar dentro do repositório.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
source = (HERE / "cronista_kit_teste.lua").read_text(encoding="utf-8")
lines = [ln.strip() for ln in source.splitlines() if ln.strip() and not ln.strip().startswith("--")]
one_line = " ".join(re.sub(r"\s+--\s.*$", "", ln) for ln in lines)
REPO_ROOT = HERE.parents[1]
requested = (
    Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "data/prod/kit-resolve/teste-linha-unica.lua"
)
target = (REPO_ROOT / requested).resolve()
if not target.is_relative_to(REPO_ROOT):
    sys.exit(f"erro: a saída deve ficar dentro do repositório ({REPO_ROOT}): {target}")
target.write_text(one_line, encoding="utf-8")
print(f"{target}: {len(one_line)} caracteres")
