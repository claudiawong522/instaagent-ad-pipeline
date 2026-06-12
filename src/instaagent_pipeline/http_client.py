from __future__ import annotations

import json
import os
import ssl
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


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    body: Any = None,
    timeout: int = 60,
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
        raise HttpClientError(f"HTTP {exc.code} for {redact_url(url)}", status=exc.code, body=parsed) from exc
    except (URLError, RemoteDisconnected) as exc:
        reason = getattr(exc, "reason", exc)
        raise HttpClientError(f"Network error for {redact_url(url)}: {reason}") from exc


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
    return ssl.create_default_context()
