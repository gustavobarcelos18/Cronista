"""CLI do Cronista (Typer). Os comandos ficam em `cronista.commands.*`; aqui só se monta o `app`."""

from __future__ import annotations

import typer

from cronista.commands import assembly, capture, devtools, narrative, packaging
from cronista.commands.common import force_utf8_output

force_utf8_output()

app = typer.Typer(help="Cronista: gameplay do OBS → timeline do Resolve.", no_args_is_help=True)

for _module in (capture, narrative, assembly, packaging, devtools):
    _module.register(app)
