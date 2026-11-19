"""Embalagem da sessão: títulos, thumbnails, Shorts e pacote de publicação (Fase 9D)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from cronista.api.context import ApiContext
from cronista.api.schemas import (
    ShortDecisionIn,
    ThumbnailChoiceIn,
    TitleChoiceIn,
)
from cronista.packaging.panel import PackagingOut, PublishOut, packaging_panel
from cronista.packaging.publish import (
    PublishError,
    build_publish_package,
    list_shorts,
    record_short_decision,
)
from cronista.packaging.service import TitleError, record_title_choice
from cronista.paths import SessionPaths, thumbnails_in
from cronista.thumbnails.render import ThumbnailError
from cronista.thumbnails.service import load_manifest, record_thumbnail_choice


def packaging_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()

    def _packaging_folders(session_id: int) -> tuple[Path, Path]:
        paths = SessionPaths.of(ctx.settings, session_id)
        return paths.packaging_dir, paths.shorts_dir

    def _packaging(db: Session, session_id: int) -> PackagingOut:
        packaging, shorts = _packaging_folders(session_id)
        return packaging_panel(db, session_id, packaging, shorts)

    @router.get("/sessions/{session_id}/packaging", response_model=PackagingOut)
    def packaging_view(session_id: int) -> PackagingOut:
        """Títulos sugeridos, thumbnails e Shorts da sessão com a escolha vigente (Fase 9D)."""
        with ctx.connect() as db:
            ctx.require_session(db, session_id)
            return _packaging(db, session_id)

    @router.post("/sessions/{session_id}/packaging/title", response_model=PackagingOut)
    def packaging_title(session_id: int, body: TitleChoiceIn) -> PackagingOut:
        """Registra o título escolhido. Só insere; o texto do criador sempre vale mais que o sugerido."""
        with ctx.connect() as db:
            ctx.require_session(db, session_id)
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

    @router.post("/sessions/{session_id}/packaging/thumbnail", response_model=PackagingOut)
    def packaging_thumbnail(session_id: int, body: ThumbnailChoiceIn) -> PackagingOut:
        """Registra a variação de thumbnail escolhida. Só insere."""
        with ctx.connect() as db:
            ctx.require_session(db, session_id)
            try:
                record_thumbnail_choice(db, session_id, _packaging_folders(session_id)[0], body.variation)
            except ThumbnailError as exc:
                raise HTTPException(422, str(exc)) from exc
            return _packaging(db, session_id)

    @router.post("/sessions/{session_id}/packaging/shorts/{key}/decision", response_model=PackagingOut)
    def packaging_short_decision(session_id: int, key: str, body: ShortDecisionIn) -> PackagingOut:
        """Aprova, rejeita ou volta a pendente um Short. Só insere."""
        with ctx.connect() as db:
            ctx.require_session(db, session_id)
            try:
                record_short_decision(db, session_id, _packaging_folders(session_id)[1], key, body.decision)
            except PublishError as exc:
                raise HTTPException(422, str(exc)) from exc
            return _packaging(db, session_id)

    @router.post("/sessions/{session_id}/packaging/publish", response_model=PublishOut)
    def packaging_publish(session_id: int) -> PublishOut:
        """Reúne título, thumbnail e Shorts aprovados na pasta de publicação (vídeo: `--video` na CLI)."""
        with ctx.connect() as db:
            ctx.require_session(db, session_id)
            packaging, shorts = _packaging_folders(session_id)
            try:
                report = build_publish_package(db, session_id, shorts, packaging)
            except PublishError as exc:
                raise HTTPException(422, str(exc)) from exc
        return PublishOut(
            directory=str(report.directory), files=report.files, missing=report.missing, ready=report.ready
        )

    @router.get("/sessions/{session_id}/packaging/thumbnails/{name}")
    def packaging_thumbnail_image(session_id: int, name: str) -> FileResponse:
        """JPEG de uma variação; só serve nomes do manifesto (nada fora da pasta de thumbnails)."""
        with ctx.connect() as db:
            ctx.require_session(db, session_id)
        folder = _packaging_folders(session_id)[0]
        try:
            allowed = {str(e["arquivo"]) for e in load_manifest(folder)}
        except ThumbnailError as exc:
            raise HTTPException(404, str(exc)) from exc
        path = thumbnails_in(folder) / name
        if name not in allowed or not path.is_file():
            raise HTTPException(404, "thumbnail não encontrada")
        return FileResponse(path, media_type="image/jpeg")

    @router.get("/sessions/{session_id}/packaging/shorts/{key}/video")
    def packaging_short_video(session_id: int, key: str) -> FileResponse:
        """MP4 de um Short renderizado (o FileResponse atende `Range`, então o player pode buscar)."""
        with ctx.connect() as db:
            ctx.require_session(db, session_id)
        try:
            entries = list_shorts(_packaging_folders(session_id)[1], session_id)
        except PublishError as exc:
            raise HTTPException(404, str(exc)) from exc
        clip = next((e.clip for e in entries if e.key == key), None)
        if clip is None or not clip.is_file():
            raise HTTPException(404, "Short não renderizado")
        return FileResponse(clip, media_type="video/mp4")

    return router
