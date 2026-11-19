"""API HTTP local (FastAPI) que o Studio consome: sessões, revisão, acabamento, embalagem e progresso.

À origem do Studio é permitido escrever (decisões, exportação, escolhas); outras origens só leem.
As rotas ficam em um router por domínio (`routes_*.py`); os modelos, em `schemas.py`."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker

from cronista.api.context import ApiContext
from cronista.api.routes_finishing import finishing_router
from cronista.api.routes_media import media_router
from cronista.api.routes_packaging import packaging_router
from cronista.api.routes_progress import progress_router
from cronista.api.routes_review import review_router
from cronista.api.routes_sessions import sessions_router
from cronista.config import Settings
from cronista.db.session import make_engine, upgrade_db
from cronista.finishing.loader import StyleLoader
from cronista.review.reexport import ProfileLoader, ReexportJobs


def create_app(
    settings: Settings,
    origins: list[str] | None = None,
    profile_loader: ProfileLoader | None = None,
    finishing_loader: StyleLoader | None = None,
) -> FastAPI:
    # Um engine só (migrado na partida) para todas as requisições; o `lifespan` o fecha ao desligar.
    engine = make_engine(settings.db_path)
    upgrade_db(engine)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(title="Cronista Engine", version="0.1.0", lifespan=lifespan)
    allowed = origins or settings.studio_origins or ["http://localhost:3000", "http://127.0.0.1:3000"]
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

    jobs = ReexportJobs(settings, profile_loader, finishing_loader)
    app.state.reexport = jobs
    ctx = ApiContext(
        settings=settings,
        factory=sessionmaker(engine, expire_on_commit=False),
        jobs=jobs,
        profile_loader=profile_loader,
        finishing_loader=finishing_loader,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.env}

    for build in (
        sessions_router,
        media_router,
        review_router,
        progress_router,
        finishing_router,
        packaging_router,
    ):
        app.include_router(build(ctx))
    return app
