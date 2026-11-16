"""Padrão de evidência e proveniência (lacuna técnica 2, histórico §36).

Todo evento derivado de análise diz de onde veio: fonte, intervalo em quadros inteiros a 60 fps, confiança,
modelo, versão e hash dos parâmetros. A 5A (objetivos) amplia isto na tabela `evidence`, com os mesmos campos.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class EvidenceSource(StrEnum):
    TRANSCRICAO = "transcricao"
    SINAL = "sinal"
    EVENTO = "evento"
    CENA = "cena"
    MARCADOR = "marcador"
    HUMANO = "humano"


def params_hash(params: dict[str, Any]) -> str:
    """Hash estável dos parâmetros de uma análise (a mesma ordem de chaves sempre dá o mesmo hash)."""
    return hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()


class Evidence(BaseModel):
    source: EvidenceSource
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)
    model: str
    model_version: str
    params_hash: str
    quote: str | None = None  # citação literal; nula se não houver fala

    @model_validator(mode="after")
    def _ordered(self) -> Evidence:
        if self.end_frame < self.start_frame:
            raise ValueError(f"intervalo invertido: {self.start_frame}..{self.end_frame}")
        return self


class AnalysisEvent(BaseModel):
    """Evento pontual ou com duração: fala, risada, grito, rotina…"""

    kind: str
    evidence: Evidence
    payload: dict[str, Any] = Field(default_factory=dict)
