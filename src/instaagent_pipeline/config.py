from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    supabase_url: str | None
    supabase_key: str | None
    foreplay_api_key: str | None
    foreplay_base_url: str
    topyappers_api_key: str | None
    topyappers_base_url: str

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            supabase_url=os.getenv("SUPABASE_URL"),
            supabase_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY"),
            foreplay_api_key=os.getenv("FOREPLAY_API_KEY"),
            foreplay_base_url=os.getenv("FOREPLAY_BASE_URL", "https://public.api.foreplay.co").rstrip("/"),
            topyappers_api_key=os.getenv("TOPYAPPERS_API_KEY"),
            topyappers_base_url=os.getenv("TOPYAPPERS_BASE_URL", "https://api.topyappers.com").rstrip("/"),
        )

