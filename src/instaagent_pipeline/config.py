from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    supabase_url: str | None
    supabase_key: str | None
    topyappers_api_key: str | None
    topyappers_base_url: str
    apify_api_key: str | None
    claude_api_key: str | None
    claude_model: str
    openrouter_api_key: str | None = None
    openrouter_model: str = "google/gemini-3-flash-preview"
    voyage_api_key: str | None = None
    embedding_model: str = "voyage-4-lite"

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        return cls(
            supabase_url=os.getenv("SUPABASE_URL"),
            supabase_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY"),
            topyappers_api_key=os.getenv("TOPYAPPERS_API_KEY"),
            topyappers_base_url=os.getenv("TOPYAPPERS_BASE_URL", "https://api.topyappers.com").rstrip("/"),
            apify_api_key=os.getenv("APIFY_API_KEY") or os.getenv("APIFY_TOKEN"),
            claude_api_key=os.getenv("CLAUDE_API_KEY"),
            claude_model=os.getenv("CLAUDE_MODEL", "claude-haiku-4-5"),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
            openrouter_model=os.getenv("OPENROUTER_MODEL", "google/gemini-3-flash-preview"),
            voyage_api_key=os.getenv("VOYAGE_API_KEY"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "voyage-4-lite"),
        )


def load_dotenv(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
