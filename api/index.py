"""Vercel Python entrypoint for the FastAPI backend.

Vercel serves this function for every /api/* request (see the rewrite in vercel.json).
The FastAPI app and its package stay in src/ — untouched — so the CLI, tests, and
pyproject packaging keep working; we just make them importable and strip the /api
prefix so the existing routes (/search, /campaigns, …) match unchanged.
"""

from __future__ import annotations

import os
import sys

# src/ is bundled into the function via `includeFiles` in vercel.json.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from instaagent_pipeline.api.app import app as _fastapi_app  # noqa: E402

_PREFIX = "/api"


async def app(scope, receive, send):
    """Thin ASGI shim: drop the leading /api so FastAPI's unprefixed routes match.

    Robust to how Vercel forwards the path — strips the prefix when present and
    passes everything else (including lifespan) straight through.
    """
    if scope["type"] in ("http", "websocket"):
        path = scope.get("path", "")
        if path == _PREFIX or path.startswith(_PREFIX + "/"):
            stripped = path[len(_PREFIX):] or "/"
            scope = {**scope, "path": stripped, "raw_path": stripped.encode("utf-8")}
    await _fastapi_app(scope, receive, send)
