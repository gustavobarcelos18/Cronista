"""Revisão e aprendizado por projeto: pesos, feedback e painel da série."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from cronista.api.context import ApiContext
from cronista.api.schemas import (
    FeedbackIn,
    FeedbackOut,
    LearningOut,
)
from cronista.db.models import Feedback, MediaFile, Project
from cronista.review.learning import MIN_DECISIONS, WEIGHT_NAMES, accept, params_for_project, propose
from cronista.review.panel import SeriesPanelOut, series_panel_full


def review_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()

    def _learning(db: Session, project_id: int) -> LearningOut:
        applied = params_for_project(db, project_id)
        current = {n: float(getattr(applied, n)) for n in WEIGHT_NAMES}
        proposal = propose(db, project_id)
        if proposal is None:
            return LearningOut(needed=MIN_DECISIONS, applied=current)
        return LearningOut(
            needed=MIN_DECISIONS,
            weights=proposal.weights,
            explanation=proposal.explanation,
            n_decisions=proposal.n_decisions,
            applied=current,
        )

    @router.get("/projects/{project_id}/learning", response_model=LearningOut)
    def get_learning(project_id: int) -> LearningOut:
        with ctx.connect() as db:
            if db.get(Project, project_id) is None:
                raise HTTPException(404, "projeto não encontrado")
            return _learning(db, project_id)

    @router.post("/projects/{project_id}/learning/accept", response_model=LearningOut)
    def accept_learning(project_id: int) -> LearningOut:
        """Aceita a proposta atual: vira calibração do projeto (só inserção); vale na próxima relevância."""
        with ctx.connect() as db:
            if db.get(Project, project_id) is None:
                raise HTTPException(404, "projeto não encontrado")
            proposal = propose(db, project_id)
            if proposal is None:
                raise HTTPException(409, f"poucas decisões (mínimo {MIN_DECISIONS}, com 5 de cada lado)")
            accept(db, project_id, proposal)
            return _learning(db, project_id)

    @router.post("/media/{media_id}/feedback", response_model=FeedbackOut, status_code=201)
    def post_feedback(media_id: int, body: FeedbackIn) -> FeedbackOut:
        """Guarda o feedback em texto livre (Q26). A interpretação por LLM local só entra após o benchmark."""
        text = body.text.strip()
        if not text:
            raise HTTPException(422, "feedback vazio")
        with ctx.connect() as db:
            media = db.get(MediaFile, media_id)
            if media is None:
                raise HTTPException(404, "arquivo não encontrado")
            row = Feedback(
                project_id=media.session.project_id,
                media_file_id=media_id,
                seg_start_s=body.seg_start_s,
                text=text,
            )
            db.add(row)
            db.commit()
            return FeedbackOut(id=row.id, interpreted=False)

    @router.get("/series", response_model=SeriesPanelOut)
    def series() -> SeriesPanelOut:
        with ctx.connect() as db:
            return series_panel_full(db)

    return router
