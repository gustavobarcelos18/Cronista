"""Painel da série (Fase 7D, plano 4.1): quanto produto já existe, por sessão e por tipo de momento.

Usa os segmentos efetivos (com as decisões do criador), então rejeitar um trecho já baixa a estimativa.
Totais e situação são por projeto (série): cada projeto é um vídeo, com a sua meta de 30 a 50 min.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.db.models import Marker, RecordingSession
from cronista.relevance.engine import Segment, kept_seconds
from cronista.review.decisions import load_effective_segments
from cronista.review.learning import params_for_project
from cronista.story.arc import MIN_CHAPTER_S, arc_complete, build_chapters
from cronista.story.service import DEFAULT_TARGET_S

TARGET_MIN = DEFAULT_TARGET_S / 60
MIN_MIN = 30.0
MAX_MIN = 50.0


Situacao = Literal["curto_ok", "abaixo_da_referencia", "no_alvo", "acima"]
"""Abaixo de 30 min: `curto_ok` se o arco está completo (histórico §40), `abaixo_da_referencia` se não."""


class SeriesRowOut(BaseModel):
    sessao: int
    gravado_h: float
    produto_min: float
    acumulado_min: float
    dias: int
    """Quantas vezes a tecla `Novo dia` foi apertada na sessão (a contagem na tela é decidida na edição)."""
    por_classe_min: dict[str, float]


class ThinChapterOut(BaseModel):
    capitulo: int
    produto_s: float


class ProjectPanelOut(BaseModel):
    projeto_id: int
    projeto: str
    total_min: float
    situacao: Situacao
    por_classe_min: dict[str, float]
    sessoes: list[SeriesRowOut]
    capitulos_com_pouco_material: list[ThinChapterOut]


class SeriesPanelOut(BaseModel):
    meta_min: float
    minimo_min: float
    maximo_min: float
    referencia_capitulo_s: float
    projetos: list[ProjectPanelOut]


def situation(total_min: float, complete_arc: bool) -> Situacao:
    if total_min < MIN_MIN:
        return "curto_ok" if complete_arc else "abaixo_da_referencia"
    return "acima" if total_min > MAX_MIN else "no_alvo"


def series_panel_full(db: Session) -> SeriesPanelOut:
    sessions_by_project: dict[int, list[RecordingSession]] = defaultdict(list)
    for session in db.scalars(select(RecordingSession).order_by(RecordingSession.id)):
        sessions_by_project[session.project_id].append(session)
    return SeriesPanelOut(
        meta_min=TARGET_MIN,
        minimo_min=MIN_MIN,
        maximo_min=MAX_MIN,
        referencia_capitulo_s=MIN_CHAPTER_S,
        projetos=[
            _project_panel(db, sessions, params_for_project(db, project_id).keep_score)
            for project_id, sessions in sessions_by_project.items()
        ],
    )


def _project_panel(db: Session, sessions: list[RecordingSession], keep_score: float) -> ProjectPanelOut:
    rows: list[SeriesRowOut] = []
    totals: dict[str, float] = {}
    files: list[tuple[int, list[Segment]]] = []
    markers: dict[str, str] = {}
    cumulative = 0.0
    for session in sessions:
        days = db.execute(
            select(Marker.marker_id, Marker.media_file_id).where(
                Marker.session_id == session.id, Marker.kind == "novo_dia"
            )
        ).all()
        markers.update({marker_id: "novo_dia" for marker_id, media_id in days if media_id is not None})
        raw = kept = 0.0
        by_class: dict[str, float] = {}
        for media in session.media_files:
            segs = load_effective_segments(db, media.id)
            if not segs:
                continue
            files.append((media.id, segs))
            raw += max(s.end_s for s in segs)
            for s in segs:
                sec = kept_seconds(s, keep_score)
                kept += sec
                if sec > 0:
                    by_class[s.classe] = by_class.get(s.classe, 0.0) + sec
        cumulative += kept
        for classe, sec in by_class.items():
            totals[classe] = totals.get(classe, 0.0) + sec
        rows.append(
            SeriesRowOut(
                sessao=session.id,
                gravado_h=round(raw / 3600, 2),
                produto_min=round(kept / 60, 1),
                acumulado_min=round(cumulative / 60, 1),
                dias=len(days),
                por_classe_min={k: round(v / 60, 1) for k, v in sorted(by_class.items())},
            )
        )
    chapters = build_chapters(files, markers, keep_score)
    total = round(cumulative / 60, 1)
    return ProjectPanelOut(
        projeto_id=sessions[0].project_id,
        projeto=sessions[0].project.name,
        total_min=total,
        situacao=situation(total, arc_complete(chapters)),
        por_classe_min={k: round(v / 60, 1) for k, v in sorted(totals.items())},
        sessoes=rows,
        capitulos_com_pouco_material=[
            ThinChapterOut(capitulo=c.number, produto_s=round(c.product_s, 2))
            for c in chapters
            if round(c.product_s, 2) < MIN_CHAPTER_S
        ],
    )
