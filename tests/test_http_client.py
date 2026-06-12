from __future__ import annotations

from instaagent_pipeline.http_client import redact_url


def test_redact_url_masks_token() -> None:
    url = "https://api.apify.com/v2/acts/foo/run-sync?token=apify_api_SECRET&waitForFinish=60"
    redacted = redact_url(url)
    assert "apify_api_SECRET" not in redacted
    assert "token=%2A%2A%2A" in redacted or "token=***" in redacted
    assert "waitForFinish=60" in redacted


def test_redact_url_masks_all_sensitive_param_names() -> None:
    url = "https://example.com/x?api_key=A&key=B&apikey=C&access_token=D&secret=E&q=ok"
    redacted = redact_url(url)
    for leaked in ("A", "B", "C", "D", "E"):
        assert f"={leaked}" not in redacted
    assert "q=ok" in redacted


def test_redact_url_leaves_clean_urls_alone() -> None:
    url = "https://api.example.com/v1/things?limit=5"
    assert redact_url(url) == url
    assert redact_url("https://api.example.com/v1/things") == "https://api.example.com/v1/things"
