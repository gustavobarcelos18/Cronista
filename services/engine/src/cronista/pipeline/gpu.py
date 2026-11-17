"""Política de GPU como porta (plano mestre, seção 4.1). As implementações reais estão em `cronista.gates`.

A regra do projeto é que **todo processamento** pausa enquanto o OBS grava ou um jogo está em tela cheia
(CLAUDE.md, "Ambientes"), então o executor consulta o gate antes de cada etapa que vai rodar (CPU ou GPU).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

from cronista.logging_setup import log_event


class GpuGate(Protocol):
    def is_free(self) -> bool:
        """True quando o processamento pode **começar** (OBS parado, sem jogo em tela cheia)."""
        ...


class AlwaysFreeGate:
    """Padrão em `dev` e nos testes: a GPU nunca está ocupada."""

    def is_free(self) -> bool:
        return True


def is_free_now(gate: GpuGate, *, working: bool) -> bool:
    """Consulta o gate. `working=True` = já estamos processando (entre blocos de uma etapa).

    Um gate pode ter `is_free_while_working()` para ignorar sinais que o próprio processamento causa (a carga
    da GPU, por exemplo: medida no meio de uma etapa de GPU, seria a da própria etapa).
    """
    if working:
        check = getattr(gate, "is_free_while_working", None)
        if callable(check):
            return bool(check())
    return gate.is_free()


def gate_reason(gate: GpuGate) -> str | None:
    """Por que a GPU está ocupada, se o gate souber dizer (`reason()` é opcional)."""
    reason = getattr(gate, "reason", None)
    return reason() if callable(reason) else None


def wait_until_free(
    gate: GpuGate,
    poll_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    *,
    working: bool = False,
    **log_fields: Any,
) -> int:
    """Bloqueia até o processamento poder rodar; devolve o número de esperas (motivo no log)."""
    waits = 0
    last_reason: str | None = None
    while not is_free_now(gate, working=working):
        waits += 1
        reason = gate_reason(gate)
        if waits == 1 or reason != last_reason:  # 6 h de OBS gravando não podem virar 4 mil linhas iguais
            log_event("gpu_ocupada_aguardando", motivo=reason, **log_fields)
            last_reason = reason
        sleep(poll_seconds)
    return waits
