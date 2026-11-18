"""Painel da série (Fase 7D, plano 4.1): quanto produto já existe, por sessão e por tipo de momento.

Usa os segmentos efetivos (com as decisões do criador), então rejeitar um trecho já baixa a estimativa.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.db.models import Marker, RecordingSession
from cronista.relevance.engine import Segment
from cronista.relevance.service import product_seconds
from cronista.review.decisions import load_effective_segments
from cronista.story.arc import MIN_CHAPTER_S, build_chapters

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


class ThinChapterOut(BaseModel):
    projeto_id: int
    projeto: str
    capitulo: int
    produto_s: float


class SeriesPanelOut(BaseModel):
    meta_min: float = TARGET_MIN
    minimo_min: float = MIN_MIN
    maximo_min: float = MAX_MIN
    total_min: float
    situacao: Literal["faltando", "no_alvo", "acima"]
    por_classe_min: dict[str, float]
    sessoes: list[SeriesRowOut]
    capitulos_com_pouco_material: list[ThinChapterOut]
    referencia_capitulo_s: float = MIN_CHAPTER_S


def series_panel_full(db: Session) -> SeriesPanelOut:
    rows: list[SeriesRowOut] = []
    totals: dict[str, float] = {}
    files_by_project: dict[int, list[tuple[int, list[Segment]]]] = defaultdict(list)
    markers_by_project: dict[int, dict[str, str]] = defaultdict(dict)
    project_names: dict[int, str] = {}
    cumulative = 0.0
    for session in db.scalars(select(RecordingSession).order_by(RecordingSession.id)):
        project_id = session.project_id
        project_names[project_id] = session.project.name
        days = db.execute(
            select(Marker.marker_id, Marker.media_file_id).where(
                Marker.session_id == session.id, Marker.kind == "novo_dia"
            )
        ).all()
        markers_by_project[project_id].update(
            {marker_id: "novo_dia" for marker_id, media_id in days if media_id is not None}
        )
        raw = kept = 0.0
        by_class: dict[str, float] = {}
        for media in session.media_files:
            segs = load_effective_segments(db, media.id)
            if not segs:
                continue
            files_by_project[project_id].append((media.id, segs))
            raw += max(s.end_s for s in segs)
            for s in segs:
                sec = product_seconds([s])
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
    total = round(cumulative / 60, 1)
    situacao: Literal["faltando", "no_alvo", "acima"] = (
        "faltando" if total < MIN_MIN else "acima" if total > MAX_MIN else "no_alvo"
    )
    thin_chapters: list[ThinChapterOut] = []
    for project_id, files in files_by_project.items():
        for chapter in build_chapters(files, markers_by_project[project_id]):
            seconds = round(chapter.product_s, 2)
            if seconds < MIN_CHAPTER_S:
                thin_chapters.append(
                    ThinChapterOut(
                        projeto_id=project_id,
                        projeto=project_names[project_id],
                        capitulo=chapter.number,
                        produto_s=seconds,
                    )
                )
    return SeriesPanelOut(
        total_min=total,
        situacao=situacao,
        por_classe_min={k: round(v / 60, 1) for k, v in sorted(totals.items())},
        sessoes=rows,
        capitulos_com_pouco_material=thin_chapters,
    )
