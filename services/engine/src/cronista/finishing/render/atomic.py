"""Escrita atômica dos renders: o FFmpeg grava em um arquivo temporário e só no fim ele vira o definitivo.

Sem isso, uma exportação cancelada (processo morto, disco cheio) deixa um clipe parcial com o nome final, e o
cache por hash o reaproveitaria para sempre.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path


def render_to(target: Path, run: Callable[[Path], None]) -> None:
    """Chama `run(temporario)` e troca o temporário por `target` só se `run` terminou sem erro.

    O temporário mantém a extensão de `target` (o FFmpeg escolhe o contêiner por ela).
    """
    partial = target.with_name(f"part-{target.name}")
    partial.unlink(missing_ok=True)
    try:
        run(partial)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
