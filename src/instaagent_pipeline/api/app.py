from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..config import Config
from ..supabase_client import SupabaseClient
from .campaigns import resume_orphaned_jobs
from .routes_campaigns import router as campaigns_router
from .routes_discover import router as discover_router
from .routes_search import router as search_router
from .routes_trends import router as trends_router


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Self-heal: re-run any scrape whose worker was killed (e.g. by this very reload) so its
    # items don't sit stuck at "processing" forever. Runs on server startup (not import, so
    # importing the module — e.g. in tests — spawns no threads); best-effort.
    # Skipped on Vercel: there each invocation is isolated and short-lived, scrapes run inline
    # (see campaigns.trigger_scrape), and background resume threads would be killed on return —
    # so orphan-resume only makes sense for a persistent local server.
    if app.state.supabase is not None and not os.getenv("VERCEL"):
        try:
            resumed = resume_orphaned_jobs(app.state.config, app.state.supabase)
            if resumed:
                print(f"[startup] resumed {resumed} interrupted scrape job(s)")
        except Exception as exc:
            print(f"[startup] orphan recovery failed: {exc}")
    yield


def create_app() -> FastAPI:
    config = Config.from_env()
    app = FastAPI(title="InstaAgent Ad Search API", lifespan=_lifespan)

    # Optional shared-secret gate (bot/scanner speed bump; see Config.api_auth_token). Registered
    # before CORS so CORS stays outermost — preflight and the 401 both keep their CORS headers.
    token = config.api_auth_token
    if token:
        expected = f"Bearer {token}"

        @app.middleware("http")
        async def require_token(request: Request, call_next):
            # Let CORS preflight and the health check through unauthenticated.
            if request.method != "OPTIONS" and request.url.path != "/health":
                if not secrets.compare_digest(request.headers.get("authorization", ""), expected):
                    return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in config.cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.config = config
    app.state.supabase = (
        SupabaseClient(config.supabase_url, config.supabase_key)
        if config.supabase_url and config.supabase_key
        else None
    )
    app.include_router(search_router)
    app.include_router(campaigns_router)
    app.include_router(discover_router)
    app.include_router(trends_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
