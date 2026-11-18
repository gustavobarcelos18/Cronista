"""Vocabulário do acabamento (Fase 8): tipos de efeito e modos. Só biblioteca padrão (sem pydantic)."""

from __future__ import annotations

from enum import StrEnum


class EffectKind(StrEnum):
    """Efeitos que o acabamento pode aplicar, cada um com modo e orçamento próprios."""

    ZOOM = "zoom"
    SHAKE = "shake"
    MUSICA = "musica"
    SFX = "sfx"
    SFX_MEME = "sfx_meme"
    PIADA_VISUAL = "piada_visual"
    CONTADOR_MORTES = "contador_mortes"
    FREEZE_TEXTO = "freeze_texto"
    BARRA_PROGRESSO = "barra_progresso"
    LEGENDA_PONTUAL = "legenda_pontual"
    CARTELA_DIA = "cartela_dia"
    COR_LUT = "cor_lut"


class EffectMode(StrEnum):
    """Os três modos da seção 6.4: só marcador, aplicado e editável no Resolve, ou renderizado pelo app."""

    SUGERIR = "sugerir"
    EDITAVEL = "editavel"
    RENDERIZADO = "renderizado"
