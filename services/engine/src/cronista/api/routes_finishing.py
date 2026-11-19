"""Exportação e acabamento da sessão (prévia, ajustes por efeito e decisões por item)."""

from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.orm import Session

from cronista.api.context import ApiContext
from cronista.api.schemas import (
    EffectSettingIn,
    EffectSettingOut,
    FinishDecisionIn,
    FinishingOut,
    FinishItemOut,
)
from cronista.assembly.plan import EditPlan
from cronista.assembly.service import assemble
from cronista.db.models import Project, RecordingSession
from cronista.domain.frames import FPS
from cronista.finishing.brand import EffectPolicy, ResolvedStyle
from cronista.finishing.effects import EffectKind
from cronista.finishing.library import Library
from cronista.finishing.overrides import (
    current_item_decisions,
    current_settings,
    record_item_decision,
    record_setting,
    source_of,
    with_overrides,
)
from cronista.finishing.plan import FinishPlan, apply_decisions, decision_key
from cronista.finishing.service import assembly_fingerprint, build_finishing
from cronista.montage import SessionPlanError
from cronista.review.panel import TARGET_MIN
from cronista.review.reexport import ExportStatus
from cronista.story.service import StoryError, StoryResult

MAX_CACHED_ASSEMBLIES = 8
"""Montagens guardadas na prévia do acabamento (uma por sessão e alvo de duração)."""


def finishing_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()

    @router.get("/sessions/{session_id}/export", response_model=ExportStatus)
    def export_status(session_id: int, serie: bool = Query(False)) -> ExportStatus:
        return ctx.jobs.status(session_id, serie)

    @router.post("/sessions/{session_id}/export", response_model=ExportStatus, status_code=202)
    def start_export(
        session_id: int, target_min: float = Query(TARGET_MIN, gt=0, le=240), serie: bool = Query(False)
    ) -> ExportStatus:
        """Re-exporta com as decisões e o roteiro atuais; o cache por hash reaproveita o que não mudou.

        Com `serie=true`, `session_id` é a sessão âncora e o vídeo cobre todas as sessões do projeto.
        """
        with ctx.connect() as db:
            if db.get(RecordingSession, session_id) is None:
                raise HTTPException(404, "sessão não encontrada")
        if not ctx.jobs.start(session_id, target_min * 60, serie):
            raise HTTPException(409, "já há uma exportação em andamento")
        return ctx.jobs.status(session_id, serie)

    assembly_cache: dict[tuple[int, float, bool], tuple[tuple[int, ...], EditPlan, StoryResult]] = {}
    assembly_lock = threading.Lock()

    def _finish_plan(
        db: Session,
        session_id: int,
        target_s: float,
        style: ResolvedStyle,
        library: Library | None,
        series: bool = False,
    ) -> FinishPlan:
        """Plano de acabamento da sessão. A montagem (história + cortes) é cara e só muda quando o banco muda:
        fica em cache por sessão e alvo, com a impressão digital das tabelas que a alimentam."""
        objectives = ctx.profile_loader() if ctx.profile_loader else ([], [])
        session = db.get(RecordingSession, session_id)
        project_id = session.project_id if session is not None and series else None
        scope_session = None if series else session_id
        key, fingerprint = (session_id, target_s, series), assembly_fingerprint(db, session_id, series)
        with assembly_lock:
            hit = assembly_cache.get(key)
        if hit is not None and hit[0] == fingerprint:
            assembled = (hit[1], hit[2])
        else:
            assembled = assemble(db, scope_session, ctx.settings, target_s, objectives, None, project_id)
            with assembly_lock:
                if len(assembly_cache) >= MAX_CACHED_ASSEMBLIES:
                    assembly_cache.pop(next(iter(assembly_cache)))
                assembly_cache[key] = (fingerprint, *assembled)
        return build_finishing(
            db, scope_session, ctx.settings, style, library, target_s, objectives, assembled, project_id
        )

    def _effect_rows(
        base: ResolvedStyle, overrides: dict[EffectKind, EffectPolicy]
    ) -> list[EffectSettingOut]:
        merged = with_overrides(base, overrides).effects
        return [
            EffectSettingOut(
                kind=kind,
                mode=merged[kind].mode,
                max_per_minute=merged[kind].max_per_minute,
                min_score=merged[kind].min_score,
                source=source_of(kind, base, overrides),
            )
            for kind in EffectKind
        ]

    @router.get("/sessions/{session_id}/finishing", response_model=FinishingOut)
    def finishing_preview(
        session_id: int, target_min: float = Query(TARGET_MIN, gt=0, le=240), serie: bool = Query(False)
    ) -> FinishingOut:
        """Prévia do acabamento: o que o plano aplicaria em cada momento, com seus ajustes e decisões."""
        loaded = ctx.finishing_loader() if ctx.finishing_loader else None
        if loaded is None:
            return FinishingOut(enabled=False)
        base, library = loaded
        with ctx.connect() as db:
            session = db.get(RecordingSession, session_id)
            if session is None:
                raise HTTPException(404, "sessão não encontrada")
            overrides = current_settings(db, session.project_id)
            decisions = current_item_decisions(db, session_id)
            style = with_overrides(base, overrides)
            try:
                plan = _finish_plan(db, session_id, target_min * 60, style, library, serie)
            except (StoryError, SessionPlanError) as exc:
                raise HTTPException(409, str(exc)) from exc
            effective = {decision_key(i): i.mode for i in apply_decisions(plan, decisions).items}
            return FinishingOut(
                enabled=True,
                series=base.series,
                max_effects_per_minute=base.max_effects_per_minute,
                has_library=library is not None,
                effects=_effect_rows(base, overrides),
                items=[
                    FinishItemOut(
                        id=i.id,
                        kind=i.kind,
                        mode=i.mode,
                        track=i.track.value,
                        start_s=round(i.start / FPS, 2),
                        duration_s=round(i.frames / FPS, 2),
                        intensity=i.intensity,
                        reason=i.reason,
                        asset_id=i.asset_id,
                        decision=decisions.get(decision_key(i)),
                        effective_mode=effective.get(decision_key(i)),
                    )
                    for i in plan.items
                ],
                summary=plan.summary(),
                warnings=plan.warnings,
            )

    @router.put("/projects/{project_id}/finishing/effects/{kind}", response_model=EffectSettingOut)
    def set_effect(project_id: int, kind: EffectKind, body: EffectSettingIn) -> EffectSettingOut:
        """Muda modo, máximo por minuto e nota mínima de um efeito para o projeto. Só insere."""
        loaded = ctx.finishing_loader() if ctx.finishing_loader else None
        if loaded is None:
            raise HTTPException(409, "acabamento não configurado (brand kit ausente)")
        with ctx.connect() as db:
            if db.get(Project, project_id) is None:
                raise HTTPException(404, "projeto não encontrado")
            try:
                record_setting(db, project_id, kind, body.mode, body.max_per_minute, body.min_score)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            overrides = current_settings(db, project_id)
        return next(r for r in _effect_rows(loaded[0], overrides) if r.kind == kind)

    @router.post("/sessions/{session_id}/finishing/items/{item_id}/decision", response_model=FinishDecisionIn)
    def decide_finishing_item(
        session_id: int,
        item_id: str,
        body: FinishDecisionIn,
        target_min: float = Query(TARGET_MIN, gt=0, le=240),
        serie: bool = Query(False),
    ) -> FinishDecisionIn:
        """Aceita uma sugestão (vira editável), tira um efeito ou volta ao padrão. Só insere.

        O item precisa existir no plano atual (mesmo alvo de duração da prévia): a decisão fica presa a ele e
        ao momento, então não vale para outro efeito que um dia caia no mesmo `id`.
        """
        loaded = ctx.finishing_loader() if ctx.finishing_loader else None
        if loaded is None:
            raise HTTPException(409, "acabamento não configurado (brand kit ausente)")
        with ctx.connect() as db:
            session = db.get(RecordingSession, session_id)
            if session is None:
                raise HTTPException(404, "sessão não encontrada")
            style = with_overrides(loaded[0], current_settings(db, session.project_id))
            try:
                plan = _finish_plan(db, session_id, target_min * 60, style, loaded[1], serie)
            except (StoryError, SessionPlanError) as exc:
                raise HTTPException(409, str(exc)) from exc
            item = next((i for i in plan.items if i.id == item_id), None)
            if item is None:
                raise HTTPException(404, f"item {item_id!r} não está no plano atual (atualize a prévia)")
            record_item_decision(db, session_id, decision_key(item), item.kind, body.decision)
        return body

    return router
