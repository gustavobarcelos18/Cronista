"""API HTTP local (FastAPI) que o Studio consome. 7A: só leitura de sessões, arquivos, jobs e marcadores."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractContextManager
from dataclasses import asdict
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from cronista.assembly.plan import EditPlan
from cronista.assembly.service import assemble
from cronista.audio.events import load_stored_events
from cronista.audio.signals import load_signal, signal_metas
from cronista.config import Settings
from cronista.db.models import Artifact, Feedback, Job, Marker, MediaFile, Project, RecordingSession
from cronista.db.session import open_db
from cronista.domain.frames import FPS
from cronista.domain.models import StageResult
from cronista.finishing.brand import EffectPolicy, ResolvedStyle
from cronista.finishing.effects import EffectKind, EffectMode
from cronista.finishing.library import Library
from cronista.finishing.loader import StyleLoader
from cronista.finishing.overrides import (
    current_item_decisions,
    current_settings,
    record_item_decision,
    record_setting,
    source_of,
    with_overrides,
)
from cronista.finishing.plan import FPS as FINISH_FPS
from cronista.finishing.plan import FinishPlan, apply_decisions, decision_key
from cronista.finishing.service import assembly_fingerprint, build_finishing
from cronista.montage import SessionPlanError, _load_source
from cronista.packaging.panel import PackagingOut, PublishOut, packaging_panel
from cronista.packaging.publish import (
    PublishError,
    build_publish_package,
    list_shorts,
    record_short_decision,
)
from cronista.packaging.service import TitleError, record_title_choice
from cronista.relevance.service import STAGE as RELEVANCE_STAGE
from cronista.relevance.service import load_segments
from cronista.review.decisions import current_decisions, decision_for, record_decision
from cronista.review.learning import MIN_DECISIONS, WEIGHT_NAMES, accept, params_for_project, propose
from cronista.review.panel import SeriesPanelOut, series_panel_full
from cronista.review.reexport import ProfileLoader, ReexportJobs
from cronista.story.models import Script
from cronista.story.script import load_script
from cronista.story.service import ScriptSaveError, StoryError, StoryResult, save_script
from cronista.thumbnails.render import ThumbnailError
from cronista.thumbnails.service import load_manifest, record_thumbnail_choice


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
    classe: str
    score: float
    razoes: list[str]
    markers: list[str]
    features: dict[str, float]
    decision: str | None = None
    adj_start_s: float | None = None
    adj_end_s: float | None = None


class ScriptOut(BaseModel):
    script: Script
    warnings: list[str] = []


class ExportStatusOut(BaseModel):
    state: Literal["idle", "running", "done", "error"]
    message: str = ""
    version: int | None = None
    reused: bool = False
    directory: str | None = None
    problems: list[str] = []
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


def _envelope(values: np.ndarray, points: int) -> list[float]:
    if len(values) == 0:
        return []
    buckets = np.array_split(np.asarray(values, dtype=np.float32), min(points, len(values)))
    return [round(float(b.max()), 1) for b in buckets]


MAX_CACHED_ASSEMBLIES = 8
"""Montagens guardadas na prévia do acabamento (uma por sessão e alvo de duração)."""

MAX_STREAM_S = 6 * 3600.0
"""Teto de um fluxo SSE: um job "running" órfão (processo morto) não prende a conexão para sempre."""


def _media_duration(db: Session, media_id: int) -> float | None:
    media = db.get(MediaFile, media_id)
    try:
        return _load_source(db, media).duration_s if media else None
    except SessionPlanError:
        return None  # ainda não ingerido: sem duração para conferir


def create_app(
    settings: Settings,
    origins: list[str] | None = None,
    profile_loader: ProfileLoader | None = None,
    finishing_loader: StyleLoader | None = None,
) -> FastAPI:
    app = FastAPI(title="Cronista Engine", version="0.1.0")
    allowed = origins or ["http://localhost:3000", "http://127.0.0.1:3000"]
    app.add_middleware(
        CORSMiddleware, allow_origins=allowed, allow_methods=["GET", "POST", "PUT"], allow_headers=["*"]
    )

    @app.middleware("http")
    async def block_foreign_writes(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Escrita só da origem do Studio: POST sem corpo é "requisição simples" e o CORS não o barra, então
        qualquer site aberto no navegador poderia disparar exportação ou aceite de pesos em 127.0.0.1."""
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin is not None and origin not in allowed:
            return JSONResponse({"detail": "origem não autorizada"}, status_code=403)
        return await call_next(request)

    with open_db(settings.db_path):  # migra uma vez; as requisições reabrem o banco sem rodar o Alembic
        pass

    def _connect() -> AbstractContextManager[Session]:
        return open_db(settings.db_path, migrate=False)

    jobs = ReexportJobs(settings, profile_loader, finishing_loader)
    app.state.reexport = jobs

    @app.get("/sessions/{session_id}/export", response_model=ExportStatusOut)
    def export_status(session_id: int) -> ExportStatusOut:
        return ExportStatusOut(**asdict(jobs.status(session_id)))

    @app.post("/sessions/{session_id}/export", response_model=ExportStatusOut, status_code=202)
    def start_export(session_id: int, target_min: float = Query(40.0, gt=0, le=240)) -> ExportStatusOut:
        """Re-exporta com as decisões e o roteiro atuais; o cache por hash reaproveita o que não mudou."""
        with _connect() as db:
            if db.get(RecordingSession, session_id) is None:
                raise HTTPException(404, "sessão não encontrada")
        if not jobs.start(session_id, target_min * 60):
            raise HTTPException(409, "já há uma exportação em andamento")
        return ExportStatusOut(**asdict(jobs.status(session_id)))

    assembly_cache: dict[tuple[int, float], tuple[tuple[int, ...], EditPlan, StoryResult]] = {}
    assembly_lock = threading.Lock()

    def _finish_plan(
        db: Session, session_id: int, target_s: float, style: ResolvedStyle, library: Library | None
    ) -> FinishPlan:
        """Plano de acabamento da sessão. A montagem (história + cortes) é cara e só muda quando o banco muda:
        fica em cache por sessão e alvo, com a impressão digital das tabelas que a alimentam."""
        objectives = profile_loader() if profile_loader else ([], [])
        key, fingerprint = (session_id, target_s), assembly_fingerprint(db, session_id)
        with assembly_lock:
            hit = assembly_cache.get(key)
        if hit is not None and hit[0] == fingerprint:
            assembled = (hit[1], hit[2])
        else:
            assembled = assemble(db, session_id, settings, target_s, objectives)
            with assembly_lock:
                if len(assembly_cache) >= MAX_CACHED_ASSEMBLIES:
                    assembly_cache.pop(next(iter(assembly_cache)))
                assembly_cache[key] = (fingerprint, *assembled)
        return build_finishing(db, session_id, settings, style, library, target_s, objectives, assembled)

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

    @app.get("/sessions/{session_id}/finishing", response_model=FinishingOut)
    def finishing_preview(session_id: int, target_min: float = Query(40.0, gt=0, le=240)) -> FinishingOut:
        """Prévia do acabamento: o que o plano aplicaria em cada momento, com seus ajustes e decisões."""
        loaded = finishing_loader() if finishing_loader else None
        if loaded is None:
            return FinishingOut(enabled=False)
        base, library = loaded
        with _connect() as db:
            session = db.get(RecordingSession, session_id)
            if session is None:
                raise HTTPException(404, "sessão não encontrada")
            overrides = current_settings(db, session.project_id)
            decisions = current_item_decisions(db, session_id)
            style = with_overrides(base, overrides)
            try:
                plan = _finish_plan(db, session_id, target_min * 60, style, library)
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
                        start_s=round(i.start / FINISH_FPS, 2),
                        duration_s=round(i.frames / FINISH_FPS, 2),
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

    @app.put("/projects/{project_id}/finishing/effects/{kind}", response_model=EffectSettingOut)
    def set_effect(project_id: int, kind: EffectKind, body: EffectSettingIn) -> EffectSettingOut:
        """Muda modo, máximo por minuto e nota mínima de um efeito para o projeto. Só insere."""
        loaded = finishing_loader() if finishing_loader else None
        if loaded is None:
            raise HTTPException(409, "acabamento não configurado (brand kit ausente)")
        with _connect() as db:
            if db.get(Project, project_id) is None:
                raise HTTPException(404, "projeto não encontrado")
            try:
                record_setting(db, project_id, kind, body.mode, body.max_per_minute, body.min_score)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            overrides = current_settings(db, project_id)
        return next(r for r in _effect_rows(loaded[0], overrides) if r.kind == kind)

    @app.post("/sessions/{session_id}/finishing/items/{item_id}/decision", response_model=FinishDecisionIn)
    def decide_finishing_item(
        session_id: int,
        item_id: str,
        body: FinishDecisionIn,
        target_min: float = Query(40.0, gt=0, le=240),
    ) -> FinishDecisionIn:
        """Aceita uma sugestão (vira editável), tira um efeito ou volta ao padrão. Só insere.

        O item precisa existir no plano atual (mesmo alvo de duração da prévia): a decisão fica presa a ele e
        ao momento, então não vale para outro efeito que um dia caia no mesmo `id`.
        """
        loaded = finishing_loader() if finishing_loader else None
        if loaded is None:
            raise HTTPException(409, "acabamento não configurado (brand kit ausente)")
        with _connect() as db:
            session = db.get(RecordingSession, session_id)
            if session is None:
                raise HTTPException(404, "sessão não encontrada")
            style = with_overrides(loaded[0], current_settings(db, session.project_id))
            try:
                plan = _finish_plan(db, session_id, target_min * 60, style, loaded[1])
            except (StoryError, SessionPlanError) as exc:
                raise HTTPException(409, str(exc)) from exc
            item = next((i for i in plan.items if i.id == item_id), None)
            if item is None:
                raise HTTPException(404, f"item {item_id!r} não está no plano atual (atualize a prévia)")
            record_item_decision(db, session_id, decision_key(item), item.kind, body.decision)
        return body

    def _packaging_folders(session_id: int) -> tuple[Path, Path]:
        return settings.data_dir / "packaging" / str(session_id), settings.data_dir / "shorts" / str(
            session_id
        )

    def _packaging(db: Session, session_id: int) -> PackagingOut:
        packaging, shorts = _packaging_folders(session_id)
        return packaging_panel(db, session_id, packaging, shorts)

    def _require_session(db: Session, session_id: int) -> None:
        if db.get(RecordingSession, session_id) is None:
            raise HTTPException(404, "sessão não encontrada")

    @app.get("/sessions/{session_id}/packaging", response_model=PackagingOut)
    def packaging_view(session_id: int) -> PackagingOut:
        """Títulos sugeridos, thumbnails e Shorts da sessão com a escolha vigente (Fase 9D)."""
        with _connect() as db:
            _require_session(db, session_id)
            return _packaging(db, session_id)

    @app.post("/sessions/{session_id}/packaging/title", response_model=PackagingOut)
    def packaging_title(session_id: int, body: TitleChoiceIn) -> PackagingOut:
        """Registra o título escolhido. Só insere; o texto do criador sempre vale mais que o sugerido."""
        with _connect() as db:
            _require_session(db, session_id)
            try:
                record_title_choice(
                    db,
                    session_id,
                    _packaging_folders(session_id)[0],
                    suggestion=body.suggestion,
                    text=body.text,
                )
            except TitleError as exc:
                raise HTTPException(422, str(exc)) from exc
            return _packaging(db, session_id)

    @app.post("/sessions/{session_id}/packaging/thumbnail", response_model=PackagingOut)
    def packaging_thumbnail(session_id: int, body: ThumbnailChoiceIn) -> PackagingOut:
        """Registra a variação de thumbnail escolhida. Só insere."""
        with _connect() as db:
            _require_session(db, session_id)
            try:
                record_thumbnail_choice(db, session_id, _packaging_folders(session_id)[0], body.variation)
            except ThumbnailError as exc:
                raise HTTPException(422, str(exc)) from exc
            return _packaging(db, session_id)

    @app.post("/sessions/{session_id}/packaging/shorts/{key}/decision", response_model=PackagingOut)
    def packaging_short_decision(session_id: int, key: str, body: ShortDecisionIn) -> PackagingOut:
        """Aprova, rejeita ou volta a pendente um Short. Só insere."""
        with _connect() as db:
            _require_session(db, session_id)
            try:
                record_short_decision(db, session_id, _packaging_folders(session_id)[1], key, body.decision)
            except PublishError as exc:
                raise HTTPException(422, str(exc)) from exc
            return _packaging(db, session_id)

    @app.post("/sessions/{session_id}/packaging/publish", response_model=PublishOut)
    def packaging_publish(session_id: int) -> PublishOut:
        """Reúne título, thumbnail e Shorts aprovados na pasta de publicação (vídeo: `--video` na CLI)."""
        with _connect() as db:
            _require_session(db, session_id)
            packaging, shorts = _packaging_folders(session_id)
            try:
                report = build_publish_package(db, session_id, shorts, packaging)
            except PublishError as exc:
                raise HTTPException(422, str(exc)) from exc
        return PublishOut(
            directory=str(report.directory), files=report.files, missing=report.missing, ready=report.ready
        )

    @app.get("/sessions/{session_id}/packaging/thumbnails/{name}")
    def packaging_thumbnail_image(session_id: int, name: str) -> FileResponse:
        """JPEG de uma variação; só serve nomes do manifesto (nada fora da pasta de thumbnails)."""
        folder = _packaging_folders(session_id)[0]
        try:
            allowed = {str(e["arquivo"]) for e in load_manifest(folder)}
        except ThumbnailError as exc:
            raise HTTPException(404, str(exc)) from exc
        path = folder / "thumbnails" / name
        if name not in allowed or not path.is_file():
            raise HTTPException(404, "thumbnail não encontrada")
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/sessions/{session_id}/packaging/shorts/{key}/video")
    def packaging_short_video(session_id: int, key: str) -> FileResponse:
        """MP4 de um Short renderizado (o FileResponse atende `Range`, então o player pode buscar)."""
        try:
            entries = list_shorts(_packaging_folders(session_id)[1], session_id)
        except PublishError as exc:
            raise HTTPException(404, str(exc)) from exc
        clip = next((e.clip for e in entries if e.key == key), None)
        if clip is None or not clip.is_file():
            raise HTTPException(404, "Short não renderizado")
        return FileResponse(clip, media_type="video/mp4")

    def _progress(session_id: int) -> ProgressOut:
        with _connect() as db:
            rows = db.execute(
                select(Job.status, Job.stage)
                .join(MediaFile, Job.media_file_id == MediaFile.id)
                .where(MediaFile.session_id == session_id)
                .order_by(Job.id)
            ).all()
        count = {k: sum(1 for st, _ in rows if st == k) for k in ("pending", "running", "done", "failed")}
        current = next((stage for st, stage in rows if st == "running"), None)
        return ProgressOut(
            total=len(rows), **count, active=bool(count["pending"] or count["running"]), current=current
        )

    @app.get("/sessions/{session_id}/progress", response_model=ProgressOut)
    def progress(session_id: int) -> ProgressOut:
        return _progress(session_id)

    @app.get("/sessions/{session_id}/progress/stream")
    def progress_stream(
        request: Request, session_id: int, interval_s: float = Query(1.0, ge=0.05, le=10)
    ) -> StreamingResponse:
        """SSE: um evento `progress` a cada mudança; encerra quando não há mais job pendente ou rodando."""

        async def events() -> AsyncIterator[str]:
            last: str | None = None
            started = time.monotonic()
            while time.monotonic() - started < MAX_STREAM_S:
                if await request.is_disconnected():
                    return  # aba fechada: libera a conexão em vez de esperar o job acabar
                snap = await run_in_threadpool(_progress, session_id)
                data = snap.model_dump_json()
                if data != last:
                    last = data
                    yield f"event: progress\ndata: {data}\n\n"
                if not snap.active:
                    break
                await asyncio.sleep(interval_s)
            yield "event: end\ndata: {}\n\n"

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

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

    @app.get("/projects/{project_id}/learning", response_model=LearningOut)
    def get_learning(project_id: int) -> LearningOut:
        with _connect() as db:
            if db.get(Project, project_id) is None:
                raise HTTPException(404, "projeto não encontrado")
            return _learning(db, project_id)

    @app.post("/projects/{project_id}/learning/accept", response_model=LearningOut)
    def accept_learning(project_id: int) -> LearningOut:
        """Aceita a proposta atual: vira calibração do projeto (só inserção); vale na próxima relevância."""
        with _connect() as db:
            if db.get(Project, project_id) is None:
                raise HTTPException(404, "projeto não encontrado")
            proposal = propose(db, project_id)
            if proposal is None:
                raise HTTPException(409, f"poucas decisões (mínimo {MIN_DECISIONS}, com 5 de cada lado)")
            accept(db, project_id, proposal)
            return _learning(db, project_id)

    @app.post("/media/{media_id}/feedback", response_model=FeedbackOut, status_code=201)
    def post_feedback(media_id: int, body: FeedbackIn) -> FeedbackOut:
        """Guarda o feedback em texto livre (Q26). A interpretação por LLM local só entra após o benchmark."""
        text = body.text.strip()
        if not text:
            raise HTTPException(422, "feedback vazio")
        with _connect() as db:
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

    @app.get("/series", response_model=SeriesPanelOut)
    def series() -> SeriesPanelOut:
        with _connect() as db:
            return series_panel_full(db)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.env}

    @app.get("/sessions", response_model=list[SessionOut])
    def list_sessions() -> list[SessionOut]:
        with _connect() as db:
            rows = db.scalars(select(RecordingSession).order_by(RecordingSession.id)).all()
            return [_session_out(s) for s in rows]

    @app.get("/sessions/{session_id}", response_model=SessionOut)
    def get_session(session_id: int) -> SessionOut:
        with _connect() as db:
            row = db.get(RecordingSession, session_id)
            if row is None:
                raise HTTPException(404, "sessão não encontrada")
            return _session_out(row)

    @app.get("/sessions/{session_id}/jobs", response_model=list[JobOut])
    def session_jobs(session_id: int) -> list[JobOut]:
        with _connect() as db:
            rows = db.scalars(
                select(Job)
                .join(MediaFile, Job.media_file_id == MediaFile.id)
                .where(MediaFile.session_id == session_id)
                .order_by(Job.id)
            ).all()
            return [
                JobOut(
                    id=j.id,
                    media_file_id=j.media_file_id,
                    stage=j.stage,
                    variant=j.variant,
                    status=j.status,
                    attempts=j.attempts,
                    error=j.error,
                )
                for j in rows
            ]

    @app.get("/sessions/{session_id}/markers", response_model=list[MarkerOut])
    def session_markers(session_id: int) -> list[MarkerOut]:
        with _connect() as db:
            rows = db.scalars(
                select(Marker).where(Marker.session_id == session_id).order_by(Marker.media_frame)
            ).all()
            return [
                MarkerOut(
                    id=m.id,
                    marker_id=m.marker_id,
                    kind=m.kind,
                    media_file_id=m.media_file_id,
                    media_frame=m.media_frame,
                    source=m.source,
                    warning=m.warning,
                )
                for m in rows
            ]

    @app.get("/sessions/{session_id}/script", response_model=ScriptOut)
    def get_script(session_id: int) -> ScriptOut:
        path = settings.data_dir / "story" / str(session_id) / "roteiro.json"
        if not path.is_file():
            raise HTTPException(404, "roteiro ainda não importado (`cronista roteiro-import`)")
        return ScriptOut(script=load_script(path))

    @app.put("/sessions/{session_id}/script", response_model=ScriptOut)
    def put_script(session_id: int, script: Script) -> ScriptOut:
        """Valida e grava o roteiro editado; a versão anterior vira `roteiro.v<N>.json`."""
        try:
            report = save_script(settings.data_dir / "story" / str(session_id), script)
        except ScriptSaveError as e:
            raise HTTPException(422, {"message": str(e), "errors": e.errors}) from e
        return ScriptOut(script=script.model_copy(update={"lines": report.lines}), warnings=report.warnings)

    @app.get("/media/{media_id}/segments", response_model=list[SegmentOut])
    def media_segments(media_id: int) -> list[SegmentOut]:
        with _connect() as db:
            if db.get(MediaFile, media_id) is None:
                raise HTTPException(404, "arquivo não encontrado")
            decisions = current_decisions(db, media_id)
            return [
                SegmentOut(
                    start_s=g.start_s,
                    end_s=g.end_s,
                    classe=g.classe,
                    score=g.score,
                    razoes=g.razoes,
                    markers=g.markers,
                    features=g.features,
                    decision=d.decision if (d := decision_for(decisions, g)) else None,
                    adj_start_s=d.start_s if d else None,
                    adj_end_s=d.end_s if d else None,
                )
                for g in load_segments(db, media_id)
            ]

    @app.post("/media/{media_id}/segments/{seg_start_s}/decision", response_model=SegmentOut)
    def decide_segment(media_id: int, seg_start_s: int, body: DecisionIn) -> SegmentOut:
        """Aceita, rejeita ou ajusta os limites de um segmento. Só insere (histórico preservado)."""
        with _connect() as db:
            if db.get(MediaFile, media_id) is None:
                raise HTTPException(404, "arquivo não encontrado")
            seg = next((g for g in load_segments(db, media_id) if g.start_s == seg_start_s), None)
            if seg is None:
                raise HTTPException(404, "segmento não encontrado")
            try:
                d = record_decision(
                    db,
                    media_id,
                    seg_start_s,
                    body.decision,
                    body.start_s,
                    body.end_s,
                    seg_end_s=seg.end_s,
                    duration_s=_media_duration(db, media_id),
                )
            except ValueError as e:
                raise HTTPException(422, str(e)) from e
            return SegmentOut(
                start_s=seg.start_s,
                end_s=seg.end_s,
                classe=seg.classe,
                score=seg.score,
                razoes=seg.razoes,
                markers=seg.markers,
                features=seg.features,
                decision=d.decision,
                adj_start_s=d.start_s,
                adj_end_s=d.end_s,
            )

    @app.get("/media/{media_id}/events", response_model=list[EventOut])
    def media_events(media_id: int) -> list[EventOut]:
        """Eventos de áudio (fala, sons, grito) em ordem de tempo; a relevância fica de fora."""
        with _connect() as db:
            if db.get(MediaFile, media_id) is None:
                raise HTTPException(404, "arquivo não encontrado")
            return [
                EventOut(
                    stage=s.stage,
                    variant=s.variant,
                    kind=s.event.kind,
                    start_s=s.event.evidence.start_frame / FPS,
                    end_s=s.event.evidence.end_frame / FPS,
                    source=s.event.evidence.source.value,
                    confidence=s.event.evidence.confidence,
                    quote=s.event.evidence.quote,
                )
                for s in load_stored_events(db, media_id)
                if s.stage != RELEVANCE_STAGE
            ]

    @app.get("/media/{media_id}/waveform", response_model=WaveformOut)
    def media_waveform(media_id: int, points: int = Query(800, ge=10, le=4000)) -> WaveformOut:
        with _connect() as db:
            if db.get(MediaFile, media_id) is None:
                raise HTTPException(404, "arquivo não encontrado")
            artifact = db.scalar(
                select(Artifact).where(
                    Artifact.media_file_id == media_id,
                    Artifact.stage == "audio_signals",
                    Artifact.variant == "",
                )
            )
            if artifact is None or not Path(artifact.result_path).is_file():
                raise HTTPException(404, "sinais de áudio ainda não calculados")
            result = StageResult.model_validate_json(Path(artifact.result_path).read_text(encoding="utf-8"))
        metas = signal_metas(result)
        out: dict[str, list[float]] = {"game": [], "mic": []}
        duration = 0.0
        for key, name in (("game", "game.energy_db"), ("mic", "mic.energy_db")):
            meta = metas.get(name)
            if meta is None:
                continue
            sig = load_signal(meta)
            out[key] = _envelope(np.asarray(sig.values), points)
            duration = max(duration, sig.end_frame / FPS)
        return WaveformOut(duration_s=duration, points=points, game=out["game"], mic=out["mic"])

    @app.get("/media/{media_id}/video")
    def media_video(media_id: int) -> FileResponse:
        """Master normalizado (H.264 MP4); o FileResponse atende `Range`, então o player pode buscar."""
        with _connect() as db:
            artifact = db.scalar(
                select(Artifact).where(
                    Artifact.media_file_id == media_id,
                    Artifact.stage == "normalize",
                    Artifact.variant == "",
                )
            )
            if artifact is None or not Path(artifact.result_path).is_file():
                raise HTTPException(404, "arquivo ainda não ingerido")
            result = StageResult.model_validate_json(Path(artifact.result_path).read_text(encoding="utf-8"))
        master = Path(str(result.data["media"]))
        if not master.is_file():
            raise HTTPException(404, "master não existe mais; rode `cronista ingest`")
        return FileResponse(master, media_type="video/mp4")

    return app


def _session_out(s: RecordingSession) -> SessionOut:
    return SessionOut(
        id=s.id,
        project_id=s.project_id,
        project=s.project.name,
        folder=s.folder,
        files=[
            MediaFileOut(id=f.id, name=Path(f.path).name, ordinal=f.ordinal, size_bytes=f.size_bytes)
            for f in s.media_files
        ],
    )
