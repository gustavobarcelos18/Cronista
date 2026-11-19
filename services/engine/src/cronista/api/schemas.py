"""Modelos de entrada e saída da API; a fonte dos contratos gerados (`cronista.contracts`)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from cronista.finishing.effects import EffectKind, EffectMode
from cronista.relevance.engine import SegmentClass
from cronista.story.models import Script


class MediaFileOut(BaseModel):
    id: int
    name: str
    ordinal: int
    size_bytes: int


class SessionOut(BaseModel):
    id: int
    project_id: int
    project: str
    folder: str
    files: list[MediaFileOut]


class JobOut(BaseModel):
    id: int
    media_file_id: int
    stage: str
    variant: str
    status: str
    attempts: int
    error: str | None


class MarkerOut(BaseModel):
    id: int
    marker_id: str
    kind: str
    media_file_id: int | None
    media_frame: int
    source: str
    warning: str | None


class SegmentOut(BaseModel):
    start_s: int
    end_s: int
    classe: SegmentClass
    score: float
    razoes: list[str]
    markers: list[str]
    features: dict[str, float]
    kept: bool
    decision: str | None = None
    adj_start_s: float | None = None
    adj_end_s: float | None = None


class ScriptOut(BaseModel):
    script: Script
    warnings: list[str] = []


class ProgressOut(BaseModel):
    """Jobs da sessão por estado; `active` vale enquanto houver job pendente ou rodando."""

    total: int
    pending: int
    running: int
    done: int
    failed: int
    active: bool
    current: str | None = None


class LearningOut(BaseModel):
    """Proposta de recalibração dos pesos por manter/tirar (7E); `weights` é nulo enquanto faltam decisões."""

    needed: int
    weights: dict[str, float] | None = None
    explanation: list[str] = []
    n_decisions: int = 0
    applied: dict[str, float] | None = None


class FeedbackIn(BaseModel):
    text: str
    seg_start_s: int | None = None


class FeedbackOut(BaseModel):
    id: int
    interpreted: bool


class DecisionIn(BaseModel):
    decision: Literal["aceito", "rejeitado", "ajustado"]
    start_s: float | None = None
    end_s: float | None = None


class EffectSettingIn(BaseModel):
    mode: EffectMode
    max_per_minute: float = Field(ge=0, le=60)
    min_score: float = Field(ge=0, le=1)


class EffectSettingOut(BaseModel):
    """Política de um efeito e de onde ela vem (padrão do app, estilo da série ou ajuste seu no Studio)."""

    kind: EffectKind
    mode: EffectMode
    max_per_minute: float
    min_score: float
    source: Literal["padrao", "serie", "criador"]


class FinishItemOut(BaseModel):
    """Um efeito planejado para um momento do vídeo, com a decisão do criador (se houver)."""

    id: str
    kind: EffectKind
    mode: EffectMode
    track: str
    start_s: float
    duration_s: float
    intensity: float
    reason: str
    asset_id: str | None = None
    decision: Literal["aceito", "removido"] | None = None
    effective_mode: EffectMode | None = None
    """Modo que vai para o pacote depois da decisão; nulo quando o item foi tirado."""


class FinishingOut(BaseModel):
    """Prévia do acabamento da sessão: políticas por efeito e o que seria aplicado, momento a momento."""

    enabled: bool
    series: str = ""
    max_effects_per_minute: float = 0
    has_library: bool = False
    effects: list[EffectSettingOut] = []
    items: list[FinishItemOut] = []
    summary: dict[str, dict[str, int]] = {}
    warnings: list[str] = []


class FinishDecisionIn(BaseModel):
    decision: Literal["aceito", "removido", "padrao"]


class TitleChoiceIn(BaseModel):
    """`suggestion` = a sugestão como está; `text` = título do criador; os dois = sugestão editada."""

    suggestion: int | None = Field(default=None, ge=1)
    text: str | None = Field(default=None, max_length=200)


class ThumbnailChoiceIn(BaseModel):
    variation: int = Field(ge=1, le=9)


class ShortDecisionIn(BaseModel):
    decision: Literal["aprovado", "rejeitado", "padrao"]


class EventOut(BaseModel):
    stage: str
    variant: str
    kind: str
    start_s: float
    end_s: float
    source: str
    confidence: float
    quote: str | None


class WaveformOut(BaseModel):
    """Envelope de energia (dBFS) por faixa, em até `points` buckets uniformes (máximo de cada bucket)."""

    duration_s: float
    points: int
    game: list[float]
    mic: list[float]
