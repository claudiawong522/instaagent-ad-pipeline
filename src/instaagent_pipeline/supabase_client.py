from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .http_client import request_json


class SupabaseClient:
    def __init__(self, url: str, key: str) -> None:
        self.url = url.rstrip("/")
        self.key = key

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def insert(self, table: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = request_json(
            "POST",
            f"{self.url}/rest/v1/{table}",
            headers=self._headers,
            body=payload,
        )
        if isinstance(response.body, list) and response.body:
            return response.body[0]
        if isinstance(response.body, dict):
            return response.body
        return {}

    def update_by_id(self, table: str, row_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = request_json(
            "PATCH",
            f"{self.url}/rest/v1/{table}",
            headers=self._headers,
            params={"id": f"eq.{quote(row_id)}"},
            body=payload,
        )
        if isinstance(response.body, list) and response.body:
            return response.body[0]
        if isinstance(response.body, dict):
            return response.body
        return {}

    def upsert(self, table: str, payload: dict[str, Any], conflict_columns: str) -> dict[str, Any]:
        headers = dict(self._headers)
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"
        response = request_json(
            "POST",
            f"{self.url}/rest/v1/{table}",
            headers=headers,
            params={"on_conflict": conflict_columns},
            body=payload,
        )
        if isinstance(response.body, list) and response.body:
            return response.body[0]
        if isinstance(response.body, dict):
            return response.body
        return {}

