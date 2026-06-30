from __future__ import annotations

import json
import os
import ssl
import time
from dataclasses import dataclass
from http.client import RemoteDisconnected
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


# Query params whose values must never appear in error messages, which are
# persisted verbatim to source_queries.error_message.
SENSITIVE_QUERY_PARAMS = {"token", "key", "apikey", "api_key", "access_token", "secret"}


@dataclass
class JsonResponse:
    status: int
    headers: dict[str, str]
    body: Any


class HttpClientError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


# HTTP statuses worth retrying: rate limit (429) and transient server errors.
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

# Provider token (found in the failed call's provider/message) -> human label for the UI.
_BILLING_PROVIDER_LABELS = (
    ("apify", "Apify (scraping)"),
    ("openrouter", "OpenRouter (AI analysis)"),
    ("voyage", "Voyage (embeddings)"),
)
# Phrases providers use when an account is out of funds or over quota. 402 (Payment Required) is the
# canonical status; some providers signal the same thing with a 403/429 carrying one of these.
_BILLING_HINTS = (
    "insufficient credit",
    "insufficient_quota",
    "out of credit",
    "payment required",
    "not enough credit",
    "negative credit",
    "add credits",
    "billing hard limit",
    "exceeded your monthly",
    "quota exceeded",
)


def is_out_of_credits(http_status: int | None, message: str) -> bool:
    """True when a provider rejected a call for lack of funds/quota (not a transient error).
    Keyed on HTTP 402, else a billing phrase in the error text — so callers can prompt a top-up
    and re-run instead of a blind retry."""
    if http_status == 402:
        return True
    text = (message or "").lower()
    return any(hint in text for hint in _BILLING_HINTS)


def credit_provider_label(text: str) -> str:
    """Map a provider name / error string to a UI-friendly provider label ('Apify (scraping)')."""
    lowered = (text or "").lower()
    return next((label for token, label in _BILLING_PROVIDER_LABELS if token in lowered), "An API")


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    body: Any = None,
    timeout: int = 60,
    retries: int = 0,
    retry_backoff: float = 2.0,
    max_retry_sleep: float = 60.0,
) -> JsonResponse:
    if params:
        query = urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{query}"

    encoded_body = None
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "instaagent-ad-pipeline/0.1",
        **dict(headers or {}),
    }
    if body is not None:
        encoded_body = json.dumps(body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")

    request = Request(url, data=encoded_body, method=method.upper(), headers=request_headers)
    attempt = 0
    while True:
        try:
            with urlopen(request, timeout=timeout, context=ssl_context()) as response:
                raw = response.read().decode("utf-8")
                parsed = json.loads(raw) if raw else None
                return JsonResponse(
                    status=response.status,
                    headers=dict(response.headers.items()),
                    body=parsed,
                )
        except HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                parsed = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                parsed = raw
            if exc.code in RETRYABLE_STATUSES and attempt < retries:
                time.sleep(_retry_delay(exc, attempt, retry_backoff, max_retry_sleep))
                attempt += 1
                continue
            raise HttpClientError(f"HTTP {exc.code} for {redact_url(url)}", status=exc.code, body=parsed) from exc
        except (URLError, RemoteDisconnected) as exc:
            if attempt < retries:
                time.sleep(min(retry_backoff ** attempt, max_retry_sleep))
                attempt += 1
                continue
            reason = getattr(exc, "reason", exc)
            raise HttpClientError(f"Network error for {redact_url(url)}: {reason}") from exc


def _retry_delay(exc: HTTPError, attempt: int, backoff: float, ceiling: float) -> float:
    """Prefer the server's Retry-After hint (seconds), else exponential backoff."""
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    if retry_after:
        try:
            return min(float(retry_after), ceiling)
        except ValueError:
            pass
    return min(backoff ** attempt, ceiling)


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    redacted = [
        (key, "***" if key.lower() in SENSITIVE_QUERY_PARAMS else value)
        for key, value in pairs
    ]
    return urlunsplit(parts._replace(query=urlencode(redacted, doseq=True)))


def ssl_context() -> ssl.SSLContext:
    if os.getenv("INSTAAGENT_INSECURE_SSL") == "1":
        return ssl._create_unverified_context()
    # macOS python.org / venv builds don't populate OpenSSL's default trust
    # store, so create_default_context() raises CERTIFICATE_VERIFY_FAILED.
    # Fall back to certifi's CA bundle when it's available.
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()
