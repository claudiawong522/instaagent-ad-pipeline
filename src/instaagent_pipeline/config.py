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
    # Web trend pages to scrape viral formats from (trend_sources.py). JSON list of
    # {"name": ..., "url": ...} via the TREND_SOURCES env var; falls back to
    # default_trend_sources() when unset. Each page is fetched, stripped to text, and parsed
    # by the LLM into formats. None means "use the built-in defaults".
    trend_sources_json: str | None = None
    # JWT that unlocks Social Growth Engineers' email-gated newsletter posts (kind:"sge_newsletter").
    # Obtained once by subscribing an email (scratchpad/sge_unlock.py); sent as the
    # newsletter_access_token cookie on read-only content fetches. Expires ~quarterly — re-run the
    # unlock to refresh. None disables the SGE newsletter source.
    sge_access_token: str | None = None
    # Relevance floor for the search-space KNN. Cosine scores scale with query length
    # (bare keywords land ~0.2 lower than multi-word queries against the verbose
    # descriptions), so the floor is set just above the true-nonsense band (~0.24):
    # 0.30 keeps a bare "watermelon"'s on-topic hits (~0.30-0.50) and the generic
    # filler below it, while still returning nothing for unrelated queries.
    search_min_similarity: float = 0.30
    # Reranker (Voyage cross-encoder) — the calibrated relevance gate that replaces
    # the length-sensitive cosine floor. Candidates are pulled from both embedding
    # spaces with no cosine floor, then reranked; only results scoring at or above
    # rerank_min_score are returned (variable count), capped by the search limit.
    rerank_model: str = "rerank-2.5"
    rerank_min_score: float = 0.5
    # How many candidates to pull per embedding space before reranking (a cost/speed
    # ceiling, not the answer count). Must be >= corpus size to avoid truncating broad
    # queries — at ~93 items, 50/space silently capped "skincare" recall. 100 covers the
    # current corpus fully and is a sane ceiling as it grows (rerank-2.5 is cheap).
    rerank_candidate_pool: int = 100
    # Browser origins allowed to call the API (CORS), comma-separated via CORS_ORIGINS.
    cors_origins: str = "http://localhost:3000"
    # Optional shared-secret that gates the API. When set (API_AUTH_TOKEN), every request must
    # carry `Authorization: Bearer <token>` (except /health and CORS preflight). It's a bot/scanner
    # speed bump, NOT a real boundary: the SPA sends it via NEXT_PUBLIC_API_TOKEN, so it's visible
    # in the browser. Unset (default) leaves the API open, so local dev and tests are unaffected.
    api_auth_token: str = ""
    # Parser-drift reminder emails (drift_alert.py), sent free over SMTP. Default is Gmail
    # (user = Gmail address, password = app password from myaccount.google.com/apppasswords);
    # any free relay works via ALERT_SMTP_HOST/PORT (e.g. Brevo's smtp-relay.brevo.com:587,
    # where the login isn't the sender — set ALERT_EMAIL_FROM to the verified sender address).
    # Port 465 speaks SSL, anything else STARTTLS. Unset creds disable sending (logged instead).
    alert_email_to: str = "instaagenttool@gmail.com"
    alert_smtp_host: str = "smtp.gmail.com"
    alert_smtp_port: int = 465
    alert_smtp_user: str | None = None
    alert_smtp_password: str | None = None
    alert_email_from: str | None = None  # defaults to alert_smtp_user when unset

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
            trend_sources_json=os.getenv("TREND_SOURCES"),
            sge_access_token=os.getenv("SGE_ACCESS_TOKEN"),
            voyage_api_key=os.getenv("VOYAGE_API_KEY"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "voyage-4-lite"),
            search_min_similarity=float(os.getenv("SEARCH_MIN_SIMILARITY", "0.30")),
            rerank_model=os.getenv("RERANK_MODEL", "rerank-2.5"),
            rerank_min_score=float(os.getenv("RERANK_MIN_SCORE", "0.5")),
            rerank_candidate_pool=int(os.getenv("RERANK_CANDIDATE_POOL", "100")),
            cors_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000"),
            api_auth_token=os.getenv("API_AUTH_TOKEN") or "",
            alert_email_to=os.getenv("ALERT_EMAIL_TO", "instaagenttool@gmail.com"),
            # `or` fallbacks (not getenv defaults): CI passes unset secrets as empty strings.
            alert_smtp_host=os.getenv("ALERT_SMTP_HOST") or "smtp.gmail.com",
            alert_smtp_port=int(os.getenv("ALERT_SMTP_PORT") or "465"),
            alert_smtp_user=os.getenv("ALERT_SMTP_USER"),
            alert_smtp_password=os.getenv("ALERT_SMTP_PASSWORD"),
            alert_email_from=os.getenv("ALERT_EMAIL_FROM"),
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
