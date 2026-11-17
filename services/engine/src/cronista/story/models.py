"""Contratos da narrativa (Fases 5 e 5A): beats, capítulos, falas do roteiro e estados de objetivo.

Sem número de dia: o capítulo é a posição na série; o número do "Dia N" é decidido na edição (plano, seção 4).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Beat(StrEnum):
    SETUP = "setup"
    CONFLITO = "conflito"
    FALHA = "falha"
    VIRADA = "virada"
    CONQUISTA = "conquista"


class ObjState(StrEnum):
    PROPOSTO = "proposto"
    EM_ANDAMENTO = "em_andamento"
    CONCLUIDO = "concluido"
    FALHOU = "falhou"
    ABANDONADO = "abandonado"
    SUSPENSO = "suspenso"
    RETOMADO = "retomado"
    INCERTO = "incerto"


class ObjKind(StrEnum):
    PRINCIPAL = "principal"
    SECUNDARIO = "secundario"
    SUBOBJETIVO = "subobjetivo"
    RESTRICAO = "restricao"


class Span(BaseModel):
    """Trecho de um arquivo em segundos inteiros (a grade da Fase 4)."""

    file_id: int
    start_s: int
    end_s: int

    @property
    def segment_id(self) -> str:
        return f"{self.file_id}:{self.start_s}"


class ScriptLine(BaseModel):
    """Uma fala sugerida, sempre ligada a um segmento (aceite da Fase 5)."""

    segment_id: str = Field(min_length=3)
    text: str = Field(min_length=1)
    kind: Literal["narracao", "antecipacao"] = "narracao"
    justification: str | None = None
    """Obrigatória na antecipação (plano 6.8): por que mostrar antes da hora."""
    est_s: float | None = None
    """Duração estimada falada; calculada na validação quando vem vazia."""
    start_s: float | None = None
    """Onde a fala entra, em segundos do arquivo; vazio = começo do primeiro espaço livre do segmento."""


class Script(BaseModel):
    version: int = 1
    provider: str = "desconhecido"
    lines: list[ScriptLine] = Field(default_factory=list)
