from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    supabase_url: str | None
    supabase_key: str | None
    apify_api_key: str | None
    claude_api_key: str | None
    claude_model: str
    openrouter_api_key: str | None = None
    openrouter_model: str = "google/gemini-3-flash-preview"
    voyage_api_key: str | None = None
    embedding_model: str = "voyage-4-lite"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-flash-latest"
    enrichment_provider: str = "openrouter"
    # Relevance floor for the search-space KNN. Cosine scores scale with query length
    # (bare keywords land ~0.2 lower than multi-word queries against the verbose
    # descriptions), so the floor is set just above the true-nonsense band (~0.24):
    # 0.30 keeps a bare "watermelon"'s on-topic hits (~0.30-0.50) and the generic
    # filler below it, while still returning nothing for unrelated queries.
    search_min_similarity: float = 0.30

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        return cls(
            supabase_url=os.getenv("SUPABASE_URL"),
            supabase_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY"),
            apify_api_key=os.getenv("APIFY_API_KEY") or os.getenv("APIFY_TOKEN"),
            claude_api_key=os.getenv("CLAUDE_API_KEY"),
            claude_model=os.getenv("CLAUDE_MODEL", "claude-haiku-4-5"),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
            openrouter_model=os.getenv("OPENROUTER_MODEL", "google/gemini-3-flash-preview"),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
            enrichment_provider=os.getenv("ENRICHMENT_PROVIDER", "openrouter"),
            voyage_api_key=os.getenv("VOYAGE_API_KEY"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "voyage-4-lite"),
            search_min_similarity=float(os.getenv("SEARCH_MIN_SIMILARITY", "0.30")),
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
