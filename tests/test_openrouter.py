from __future__ import annotations

from instaagent_pipeline.openrouter import openrouter_json_body, parse_json_response


def test_parse_json_response_rejects_invalid_json() -> None:
    body = {"choices": [{"message": {"content": "not json"}}]}
    try:
        parse_json_response(body)
    except RuntimeError as exc:
        assert "invalid JSON" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_parse_json_response_handles_content_part_lists() -> None:
    body = {"choices": [{"message": {"content": [{"type": "text", "text": "{\"transcript_text\": null}"}]}}]}

    assert parse_json_response(body) == {"transcript_text": None}


def test_openrouter_json_body_builds_strict_schema_envelope() -> None:
    schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    body = openrouter_json_body(
        model="google/gemini-3-flash",
        messages=[{"role": "user", "content": "hi"}],
        schema=schema,
        schema_name="thing",
        max_tokens=100,
    )
    assert body["model"] == "google/gemini-3-flash"
    assert body["max_tokens"] == 100
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "thing", "strict": True, "schema": schema},
    }


def test_openrouter_json_body_omits_max_tokens_by_default() -> None:
    body = openrouter_json_body(
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        schema={"type": "object"},
        schema_name="thing",
    )
    assert "max_tokens" not in body
