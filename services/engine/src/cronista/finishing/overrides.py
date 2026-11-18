"""Ajustes do criador no Studio sobre o acabamento (Fase 8E), guardados só por inserção (padrão da 7C).

Duas camadas por cima do brand kit e da série (YAML versionado): o **ajuste de um efeito** (modo, máximo por
minuto, nota mínima), por projeto, e a **decisão sobre um item** do plano (aceitar uma sugestão, tirar
um efeito), por sessão. A última linha de cada chave vale; nada é apagado, então dá para ver o histórico.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.db.models import FinishingDecision, FinishingSetting
from cronista.finishing.brand import DEFAULT_EFFECTS, EffectPolicy, ResolvedStyle
from cronista.finishing.effects import EffectKind, EffectMode
from cronista.finishing.plan import DECISIONS

DEFAULT_DECISION = "padrao"
"""Volta ao que o plano decidiu (a linha continua guardada; só deixa de valer como decisão)."""


def record_setting(
    db: Session,
    project_id: int,
    kind: EffectKind,
    mode: EffectMode,
    max_per_minute: float,
    min_score: float,
) -> FinishingSetting:
    """Valida pelo mesmo modelo do brand kit (limites incluídos) e insere a linha."""
    policy = EffectPolicy(mode=mode, max_per_minute=max_per_minute, min_score=min_score)
    row = FinishingSetting(
        project_id=project_id,
        kind=kind.value,
        mode=policy.mode.value,
        max_per_minute=policy.max_per_minute,
        min_score=policy.min_score,
    )
    db.add(row)
    db.commit()
    return row


def current_settings(db: Session, project_id: int) -> dict[EffectKind, EffectPolicy]:
    """Ajuste vigente por tipo de efeito (a última linha). Linha de tipo desconhecido é ignorada."""
    rows = db.scalars(
        select(FinishingSetting)
        .where(FinishingSetting.project_id == project_id)
        .order_by(FinishingSetting.id)
    )
    out: dict[EffectKind, EffectPolicy] = {}
    for row in rows:
        try:
            out[EffectKind(row.kind)] = EffectPolicy(
                mode=EffectMode(row.mode), max_per_minute=row.max_per_minute, min_score=row.min_score
            )
        except ValueError:
            continue
    return out


def with_overrides(style: ResolvedStyle, overrides: dict[EffectKind, EffectPolicy]) -> ResolvedStyle:
    """O estilo com os ajustes do criador por cima (o original não muda)."""
    return style.model_copy(update={"effects": {**style.effects, **overrides}})


def source_of(kind: EffectKind, base: ResolvedStyle, overrides: dict[EffectKind, EffectPolicy]) -> str:
    """De onde vem a política do efeito: `criador` (Studio), `serie` (YAML da série) ou `padrao`."""
    if kind in overrides:
        return "criador"
    return "serie" if base.series and base.effects.get(kind) != DEFAULT_EFFECTS.get(kind) else "padrao"


def record_item_decision(
    db: Session, session_id: int, item_key: str, kind: EffectKind, decision: str
) -> FinishingDecision:
    if decision not in DECISIONS and decision != DEFAULT_DECISION:
        raise ValueError(f"decisão inválida: {decision!r}")
    row = FinishingDecision(session_id=session_id, item_key=item_key, kind=kind.value, decision=decision)
    db.add(row)
    db.commit()
    return row


def current_item_decisions(db: Session, session_id: int) -> dict[str, str]:
    """Decisão vigente por `decision_key` (`aceito` ou `removido`); `padrao` apaga a decisão anterior."""
    rows = db.scalars(
        select(FinishingDecision)
        .where(FinishingDecision.session_id == session_id)
        .order_by(FinishingDecision.id)
    )
    latest = {r.item_key: r.decision for r in rows}
    return {k: v for k, v in latest.items() if v in DECISIONS}
