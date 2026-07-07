from __future__ import annotations

import os
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import requests
from requests.adapters import HTTPAdapter

from .http_client import HttpClientError, JsonResponse, redact_url, request_json, ssl_context

# Writes are not idempotent-free but our upserts/inserts are safe to repeat, so retry transient
# network drops (e.g. "[Errno 54] Connection reset by peer" mid-scrape). Without this a single reset
# aborts a whole scrape and discards ads Apify already returned and we already paid for.
_WRITE_RETRIES = 4


class SupabaseClient:
    def __init__(self, url: str, key: str) -> None:
        self.url = normalize_supabase_url(url)
        self.key = key
        self._verify = os.getenv("INSTAAGENT_INSECURE_SSL") != "1"
        # A pooled keep-alive session for the read path (select/rpc). PostgREST is
        # remote, so a fresh TLS handshake per call dominates latency; reusing
        # connections cuts ~0.5s off every read. pool_maxsize covers the enrichment
        # thread pool; requests.Session is thread-safe for concurrent requests.
        self._session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=16, pool_maxsize=32, max_retries=0)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _reset_session(self) -> None:
        """Drop all pooled connections and start fresh. Used to escape a PostgREST
        replica whose schema cache is stale (it 404s a freshly-added RPC); a new
        connection may land on a healthy replica."""
        try:
            self._session.close()
        except Exception:
            pass
        self._session = self._build_session()

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def _session_request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        timeout: int = 60,
    ) -> JsonResponse:
        """Perform a read over the pooled session, mirroring request_json's contract
        (returns JsonResponse, raises HttpClientError) so callers are unchanged."""
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            resp = self._session.request(
                method.upper(),
                url,
                headers=self._headers,
                params=clean_params or None,
                json=json_body,
                timeout=timeout,
                verify=self._verify,
            )
        except requests.RequestException as exc:
            raise HttpClientError(f"Network error for {redact_url(url)}: {exc}") from exc
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise HttpClientError(
                f"HTTP {resp.status_code} for {redact_url(resp.url)}", status=resp.status_code, body=body
            )
        body = resp.json() if resp.content else None
        return JsonResponse(status=resp.status_code, headers=dict(resp.headers), body=body)

    def insert(self, table: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = request_json(
            "POST",
            f"{self.url}/rest/v1/{table}",
            headers=self._headers,
            body=payload,
            retries=_WRITE_RETRIES,
        )
        if isinstance(response.body, list) and response.body:
            return response.body[0]
        if isinstance(response.body, dict):
            return response.body
        return {}

    def update_by_id(self, table: str, row_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.update_by_column(table, "id", row_id, payload)

    def update_by_column(self, table: str, column: str, value: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = request_json(
            "PATCH",
            f"{self.url}/rest/v1/{table}",
            headers=self._headers,
            params={column: f"eq.{quote(value)}"},
            body=payload,
            retries=_WRITE_RETRIES,
        )
        if isinstance(response.body, list) and response.body:
            return response.body[0]
        if isinstance(response.body, dict):
            return response.body
        return {}

    def upsert(
        self,
        table: str,
        payload: dict[str, Any] | list[dict[str, Any]],
        conflict_columns: str,
    ) -> dict[str, Any]:
        headers = dict(self._headers)
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"
        response = request_json(
            "POST",
            f"{self.url}/rest/v1/{table}",
            headers=headers,
            params={"on_conflict": conflict_columns},
            body=payload,
            retries=_WRITE_RETRIES,
        )
        if isinstance(response.body, list) and response.body:
            return response.body[0]
        if isinstance(response.body, dict):
            return response.body
        return {}

    def upload_object(
        self,
        bucket: str,
        path: str,
        data: bytes,
        content_type: str,
        *,
        timeout: int = 120,
    ) -> str:
        """Upload raw bytes to Supabase Storage (upsert) and return the public URL."""
        url = f"{self.url}/storage/v1/object/{bucket}/{path}"
        request = Request(
            url,
            data=data,
            method="POST",
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": content_type,
                "x-upsert": "true",
                # Content-addressed media never changes once uploaded, so let Supabase's
                # CDN cache it forever. Without this the default is `no-cache`, forcing every
                # play (and every `<video>` range request) to cold-fetch the slow origin.
                "Cache-Control": "public, max-age=31536000, immutable",
            },
        )
        try:
            with urlopen(request, timeout=timeout, context=ssl_context()) as response:
                response.read()
        except HTTPError as exc:
            raise HttpClientError(
                f"Storage upload failed (HTTP {exc.code}) for {bucket}/{path}", status=exc.code
            ) from exc
        except URLError as exc:
            raise HttpClientError(
                f"Storage upload network error for {bucket}/{path}: {getattr(exc, 'reason', exc)}"
            ) from exc
        return f"{self.url}/storage/v1/object/public/{bucket}/{path}"

    # PostgREST runs behind a load balancer; a replica with a stale schema cache 404s
    # a recently-added function. Retry on a fresh connection (new replica) before giving up.
    RPC_SCHEMA_RETRY_STATUSES = frozenset({404, 502, 503, 504})
    RPC_MAX_ATTEMPTS = 6

    def rpc(self, fn: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        # Calls a Postgres function exposed through PostgREST, e.g. pgvector KNN.
        url = f"{self.url}/rest/v1/rpc/{fn}"
        last_error: HttpClientError | None = None
        for attempt in range(self.RPC_MAX_ATTEMPTS):
            try:
                response = self._session_request("POST", url, json_body=params)
                break
            except HttpClientError as exc:
                if exc.status in self.RPC_SCHEMA_RETRY_STATUSES and attempt < self.RPC_MAX_ATTEMPTS - 1:
                    last_error = exc
                    self._reset_session()
                    time.sleep(0.25 * (attempt + 1))
                    continue
                raise
        else:  # pragma: no cover - loop always breaks or raises
            raise last_error  # type: ignore[misc]
        if isinstance(response.body, list):
            return [row for row in response.body if isinstance(row, dict)]
        if isinstance(response.body, dict):
            return [response.body]
        return []

    def select(self, table: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        response = self._session_request(
            "GET",
            f"{self.url}/rest/v1/{table}",
            params=params,
        )
        if isinstance(response.body, list):
            return [row for row in response.body if isinstance(row, dict)]
        return []

    def select_by_ids(
        self, table: str, id_column: str, ids: list[str], columns: str
    ) -> dict[str, dict[str, Any]]:
        """Fetch rows whose id_column is in `ids`, keyed by that id. [] ids → {}."""
        if not ids:
            return {}
        rows = self.select(
            table,
            {"select": columns, id_column: f"in.({','.join(ids)})", "limit": str(len(ids))},
        )
        return {str(row.get(id_column)): row for row in rows if row.get(id_column)}

    def delete(self, table: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        # PostgREST requires at least one filter in params, otherwise it refuses
        # to delete the whole table. Callers always pass eq filters.
        response = request_json(
            "DELETE",
            f"{self.url}/rest/v1/{table}",
            headers=self._headers,
            params=params,
        )
        if isinstance(response.body, list):
            return [row for row in response.body if isinstance(row, dict)]
        return []


def normalize_supabase_url(url: str) -> str:
    cleaned = url.rstrip("/")
    suffix = "/rest/v1"
    if cleaned.endswith(suffix):
        return cleaned[: -len(suffix)]
    return cleaned
