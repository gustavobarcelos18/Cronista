"""Política de GPU como porta (plano mestre, seção 4.1). As implementações reais estão em `cronista.gates`."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

from cronista.logging_setup import log_event


class GpuGate(Protocol):
    def is_free(self) -> bool:
        """True quando o processamento com GPU pode rodar (OBS parado, sem jogo em tela cheia)."""
        ...


class AlwaysFreeGate:
    """Padrão em `dev` e nos testes: a GPU nunca está ocupada."""

    def is_free(self) -> bool:
        return True


def gate_reason(gate: GpuGate) -> str | None:
    """Por que a GPU está ocupada, se o gate souber dizer (`reason()` é opcional)."""
    reason = getattr(gate, "reason", None)
    return reason() if callable(reason) else None


def wait_until_free(
    gate: GpuGate,
    poll_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    **log_fields: Any,
) -> int:
    """Bloqueia até a GPU ficar livre; devolve quantas vezes esperou. Registra o motivo a cada espera."""
    waits = 0
    while not gate.is_free():
        waits += 1
        log_event("gpu_ocupada_aguardando", motivo=gate_reason(gate), **log_fields)
        sleep(poll_seconds)
    return waits
