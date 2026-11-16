"""Feedback ao criador: um som curto por toque (ele não está olhando para o terminal) + linha no console."""

from __future__ import annotations

import sys
from collections.abc import Callable

import typer

from cronista.domain.models import MarkerKind

# (frequência em Hz, duração em ms). Tons diferentes por tipo: dá para saber o que foi registrado de ouvido.
TONES: dict[MarkerKind, tuple[int, int]] = {
    MarkerKind.MOMENTO: (880, 90),
    MarkerKind.NOVO_DIA: (660, 220),
    MarkerKind.MORTE_FALHA: (330, 150),
    MarkerKind.ENGRACADO: (1040, 90),
    MarkerKind.CONQUISTA: (1320, 150),
    MarkerKind.CONSTRUCAO: (740, 120),
    MarkerKind.FOTO_PROGRESSO: (990, 60),
    MarkerKind.CINEMATICA: (600, 150),
}
WARN_TONE = (200, 350)


def _default_beep(frequency: int, duration_ms: int) -> None:
    try:
        import winsound  # só existe no Windows

        winsound.Beep(frequency, duration_ms)
    except ImportError:
        sys.stderr.write("\a")


class ConsoleFeedback:
    def __init__(self, beep: Callable[[int, int], None] = _default_beep, quiet: bool = False) -> None:
        self._beep, self._quiet = beep, quiet

    def _sound(self, tone: tuple[int, int]) -> None:
        if not self._quiet:
            self._beep(*tone)

    def marked(self, kind: MarkerKind, detail: str = "") -> None:
        suffix = f" ({detail})" if detail else ""
        typer.echo(f"  ✓ {kind.value}{suffix}")
        self._sound(TONES[kind])
        if kind is MarkerKind.CONSTRUCAO and detail == "fim":
            self._sound(TONES[kind])  # fim = dois toques, para diferenciar do início

    def warn(self, message: str) -> None:
        typer.echo(f"  ! {message}", err=True)
        self._sound(WARN_TONE)

    def info(self, message: str) -> None:
        typer.echo(message)
