from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import Config
from ..supabase_client import SupabaseClient
from .campaigns import resume_orphaned_jobs
from .routes_campaigns import router as campaigns_router
from .routes_discover import router as discover_router
from .routes_search import router


def create_app() -> FastAPI:
    config = Config.from_env()
    app = FastAPI(title="InstaAgent Ad Search API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
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
    app.include_router(router)
    app.include_router(campaigns_router)
    app.include_router(discover_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # Self-heal: re-run any scrape whose worker was killed (e.g. by this very reload) so its
    # items don't sit stuck at "processing" forever. Runs on every boot; best-effort.
    if app.state.supabase is not None:
        try:
            resumed = resume_orphaned_jobs(config, app.state.supabase)
            if resumed:
                print(f"[startup] resumed {resumed} interrupted scrape job(s)")
        except Exception as exc:
            print(f"[startup] orphan recovery failed: {exc}")

    return app


app = create_app()
