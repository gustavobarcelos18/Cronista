"""Feedback ao criador: um som curto por toque (ele não está olhando para o terminal) + linha no console."""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

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
    if sys.platform != "win32":  # o mypy entende esta guarda: `winsound.Beep` não existe fora do Windows
        sys.stderr.write("\a")
        return
    import winsound

    with contextlib.suppress(RuntimeError):  # sem dispositivo de áudio: a mensagem no console basta
        winsound.Beep(frequency, duration_ms)


class ConsoleFeedback:
    """Mensagem no console + tom. O tom toca em uma thread própria (uma fila, na ordem): `winsound.Beep` é
    síncrono e, no laço asyncio, atrasaria o carimbo dos eventos do OBS (pausa, divisão de arquivo)."""

    def __init__(self, beep: Callable[[int, int], None] = _default_beep, quiet: bool = False) -> None:
        self._beep, self._quiet = beep, quiet
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cronista-beep")

    def _sound(self, tone: tuple[int, int]) -> None:
        if not self._quiet:
            self._pool.submit(self._beep, *tone)

    def close(self) -> None:
        """Espera os tons pendentes terminarem (chamar ao sair)."""
        self._pool.shutdown(wait=True)

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
