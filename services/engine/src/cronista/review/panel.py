"""Painel da série (Fase 7D, plano 4.1): quanto produto já existe, por sessão e por tipo de momento.

Usa os segmentos efetivos (com as decisões do criador), então rejeitar um trecho já baixa a estimativa.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cronista.db.models import Marker, RecordingSession
from cronista.relevance.service import product_seconds
from cronista.review.decisions import load_effective_segments

TARGET_MIN = 40.0
MIN_MIN = 30.0
MAX_MIN = 50.0


class SeriesRowOut(BaseModel):
    sessao: int
    gravado_h: float
    produto_min: float
    acumulado_min: float
    dias: int
    """Quantas vezes a tecla `Novo dia` foi apertada na sessão (a contagem na tela é decidida na edição)."""
    por_classe_min: dict[str, float]


class SeriesPanelOut(BaseModel):
    meta_min: float = TARGET_MIN
    minimo_min: float = MIN_MIN
    maximo_min: float = MAX_MIN
    total_min: float
    situacao: Literal["faltando", "no_alvo", "acima"]
    por_classe_min: dict[str, float]
    sessoes: list[SeriesRowOut]


def series_panel_full(db: Session) -> SeriesPanelOut:
    rows: list[SeriesRowOut] = []
    totals: dict[str, float] = {}
    cumulative = 0.0
    for session in db.scalars(select(RecordingSession).order_by(RecordingSession.id)):
        raw = kept = 0.0
        by_class: dict[str, float] = {}
        for media in session.media_files:
            segs = load_effective_segments(db, media.id)
            if not segs:
                continue
            raw += max(s.end_s for s in segs)
            for s in segs:
                sec = product_seconds([s])
                kept += sec
                if sec > 0:
                    by_class[s.classe] = by_class.get(s.classe, 0.0) + sec
        cumulative += kept
        days = db.scalar(
            select(func.count())
            .select_from(Marker)
            .where(Marker.session_id == session.id, Marker.kind == "novo_dia")
        )
        for classe, sec in by_class.items():
            totals[classe] = totals.get(classe, 0.0) + sec
        rows.append(
            SeriesRowOut(
                sessao=session.id,
                gravado_h=round(raw / 3600, 2),
                produto_min=round(kept / 60, 1),
                acumulado_min=round(cumulative / 60, 1),
                dias=int(days or 0),
                por_classe_min={k: round(v / 60, 1) for k, v in sorted(by_class.items())},
            )
        )
    total = round(cumulative / 60, 1)
    situacao: Literal["faltando", "no_alvo", "acima"] = (
        "faltando" if total < MIN_MIN else "acima" if total > MAX_MIN else "no_alvo"
    )
    return SeriesPanelOut(
        total_min=total,
        situacao=situacao,
        por_classe_min={k: round(v / 60, 1) for k, v in sorted(totals.items())},
        sessoes=rows,
    )
