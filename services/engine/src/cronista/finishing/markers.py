"""Marcadores das sugestões de acabamento (Fase 8D): o modo `sugerir` vira só marcador, nunca efeito aplicado.

Só biblioteca padrão. O pacote de exportação converte `SuggestionMarker` em `TimelineMarker` (Lua do Resolve).
"""

from __future__ import annotations

from dataclasses import dataclass

from cronista.domain.frames import FPS
from cronista.finishing.effects import EffectKind, EffectMode
from cronista.finishing.plan import FinishItem, FinishPlan

SUGGESTION_COLORS: dict[EffectKind, str] = {
    EffectKind.ZOOM: "Sky",
    EffectKind.SHAKE: "Rose",
    EffectKind.SFX: "Lemon",
    EffectKind.SFX_MEME: "Lavender",
    EffectKind.PIADA_VISUAL: "Sand",
    EffectKind.FREEZE_TEXTO: "Mint",
    EffectKind.CONTADOR_MORTES: "Cocoa",
    EffectKind.MUSICA: "Cream",
}
"""Cores que não repetem as dos marcadores do criador (Red, Yellow, Green, Purple, Cyan, Pink...)."""

SUGGESTION_NAMES: dict[EffectKind, str] = {
    EffectKind.ZOOM: "Sugestão: zoom",
    EffectKind.SHAKE: "Sugestão: tremor",
    EffectKind.SFX: "Sugestão: efeito sonoro",
    EffectKind.SFX_MEME: "Sugestão: som de meme",
    EffectKind.PIADA_VISUAL: "Sugestão: piada visual",
    EffectKind.FREEZE_TEXTO: "Sugestão: congelar + texto",
    EffectKind.CONTADOR_MORTES: "Sugestão: contador de mortes",
    EffectKind.MUSICA: "Sugestão: música",
}


@dataclass(frozen=True)
class SuggestionMarker:
    frame: int
    color: str
    name: str
    note: str
    custom: str


def describe(item: FinishItem) -> str:
    """Texto do marcador: o que fazer, com que intensidade e de onde sai o áudio."""
    parts = [item.reason, f"intensidade {item.intensity:.2f}"]
    if item.frames:
        parts.append(f"{item.frames / FPS:.1f} s")
    if item.asset_id:
        parts.append(f"item {item.asset_id}")
    parts += [f"{k}={v}" for k, v in sorted(item.params.items())]
    return "; ".join(parts)


def suggestion_markers(plan: FinishPlan) -> list[SuggestionMarker]:
    """Um marcador por item em modo `sugerir`, em ordem de quadro."""
    out = [
        SuggestionMarker(
            frame=item.start,
            color=SUGGESTION_COLORS.get(item.kind, "Cream"),
            name=SUGGESTION_NAMES.get(item.kind, f"Sugestão: {item.kind.value}"),
            note=describe(item),
            custom=f"acabamento|{item.id}",
        )
        for item in plan.items
        if item.mode == EffectMode.SUGERIR
    ]
    return sorted(out, key=lambda m: (m.frame, m.custom))
