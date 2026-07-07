"""Shared FastAPI request helpers for all route modules."""

from __future__ import annotations

from fastapi import HTTPException, Request

from ..supabase_client import SupabaseClient


def require_supabase(request: Request) -> SupabaseClient:
    supabase = request.app.state.supabase
    if supabase is None:
        raise HTTPException(503, "Supabase is not configured (set SUPABASE_URL and a key).")
    return supabase
