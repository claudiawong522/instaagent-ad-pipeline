"""Shared OpenRouter chat-completions plumbing.

Every text-LLM call in the pipeline goes through OpenRouter's /chat/completions with a
strict JSON-schema response_format. This module owns the endpoint constants, the request
envelope, and the response parsing so feature modules don't each hand-roll them.
"""

from __future__ import annotations

import json
from typing import Any

from .config import Config
from .http_client import request_json


OPENROUTER_PROVIDER = "openrouter"
OPENROUTER_BASE_URL = "https://openrouter.ai"
OPENROUTER_CHAT_COMPLETIONS_ENDPOINT = "/api/v1/chat/completions"
OPENROUTER_CHAT_URL = f"{OPENROUTER_BASE_URL}{OPENROUTER_CHAT_COMPLETIONS_ENDPOINT}"


def openrouter_json_body(
    *,
    model: str,
    messages: list[dict[str, Any]],
    schema: dict[str, Any],
    schema_name: str,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """The chat-completions request envelope for a strict JSON-schema response."""
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        },
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    return body


def openrouter_json_call(
    config: Config,
    *,
    prompt: str,
    schema: dict[str, Any],
    schema_name: str,
    empty_error: str,
    model: str | None = None,
    max_tokens: int | None = None,
    timeout: int,
) -> dict[str, Any]:
    """One text-prompt → strict-JSON call: request, parse, raise `empty_error` on no JSON."""
    response = request_json(
        "POST",
        OPENROUTER_CHAT_URL,
        headers={"Authorization": f"Bearer {config.openrouter_api_key}"},
        body=openrouter_json_body(
            model=model or config.openrouter_model,
            messages=[{"role": "user", "content": prompt}],
            schema=schema,
            schema_name=schema_name,
            max_tokens=max_tokens,
        ),
        timeout=timeout,
    )
    analysis = parse_json_response(response.body)
    if not isinstance(analysis, dict):
        raise RuntimeError(empty_error)
    return analysis


def parse_json_response(body: Any) -> dict[str, Any] | None:
    """Extract the JSON object from choices[0].message.content, or None if absent."""
    if not isinstance(body, dict):
        return None
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        content = "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    if not isinstance(content, str) or not content.strip():
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenRouter returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        return None
    return parsed


def openrouter_usage(body: Any) -> dict[str, Any]:
    if isinstance(body, dict) and isinstance(body.get("usage"), dict):
        return body["usage"]
    return {}
