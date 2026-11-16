"""Hotkeys globais com `pynput` (Windows). O pynput só é importado ao usar: em Linux sem display ele falha."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cronista.domain.models import MarkerKind

REQUIRED = (MarkerKind.MOMENTO, MarkerKind.NOVO_DIA)


class HotkeyConfigError(ValueError):
    pass


def resolve_hotkeys(config: dict[str, str | None]) -> dict[MarkerKind, str]:
    """Config (nome do tipo → tecla) → tecla por tipo. Valida nomes e obrigatórias; `None` desliga."""
    keys: dict[MarkerKind, str] = {}
    for name, combo in config.items():
        try:
            kind = MarkerKind(name)
        except ValueError as exc:
            valid = ", ".join(k.value for k in MarkerKind)
            raise HotkeyConfigError(f"tecla para tipo desconhecido '{name}' (válidos: {valid})") from exc
        if combo:
            keys[kind] = combo
    for kind in REQUIRED:
        if kind not in keys:
            raise HotkeyConfigError(f"a tecla '{kind.value}' é obrigatória (plano mestre, seção 4)")
    combos = list(keys.values())
    if len(set(combos)) != len(combos):
        raise HotkeyConfigError("duas ações com a mesma tecla")
    return keys


class PynputHotkeys:
    def __init__(self, keys: dict[MarkerKind, str]) -> None:
        self._keys = keys
        self._listener: Any = None

    def start(self, on_press: Callable[[MarkerKind], None]) -> None:
        from pynput import keyboard

        def binding(kind: MarkerKind) -> Callable[[], None]:
            return lambda: on_press(kind)

        # `GlobalHotKeys` valida a sintaxe das teclas e levanta ValueError se alguma estiver errada.
        self._listener = keyboard.GlobalHotKeys({combo: binding(kind) for kind, combo in self._keys.items()})
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
