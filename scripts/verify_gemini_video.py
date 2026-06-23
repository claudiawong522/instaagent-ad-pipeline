#!/usr/bin/env python3
"""Verify the Gemini API key can ingest and reason over a video.

Pure-stdlib, no SDK. Loads GEMINI_API_KEY from .env, sends a video to the
Gemini generateContent endpoint as inline base64 data, and prints the model's
description back so you can confirm the video was actually processed (not just
that the key authenticates).

Usage:
    python scripts/verify_gemini_video.py [VIDEO_URL_OR_PATH] [--model MODEL]

Defaults to a small public sample video and gemini-flash-latest.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

def _ssl_context() -> ssl.SSLContext:
    """macOS system Python often lacks CA certs; fall back to certifi's bundle."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_CONTEXT = _ssl_context()

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_VIDEO = "https://storage.googleapis.com/cloud-samples-data/generative-ai/video/pixel8.mp4"
DEFAULT_MODEL = "gemini-flash-latest"
PROMPT = (
    "Watch this video and prove you actually processed the footage. "
    "In 3-4 sentences, describe the scenes chronologically, name any visible "
    "objects/people/text, and transcribe any spoken or on-screen words."
)


def load_env(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def fetch_bytes(url: str, timeout: int = 120) -> bytes:
    req = Request(url, headers={"User-Agent": "instaagent-gemini-verify/0.1"})
    with urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
        return resp.read()


def load_video(source: str) -> bytes:
    if source.startswith(("http://", "https://")):
        print(f"Downloading sample video: {source}")
        data = fetch_bytes(source)
    else:
        print(f"Reading local video: {source}")
        data = Path(source).read_bytes()
    print(f"Video size: {len(data) / 1024 / 1024:.2f} MiB")
    return data


def post_json(url: str, api_key: str, payload: dict, timeout: int = 300) -> dict:
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
            return json.loads(resp.read())
    except HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise SystemExit(f"Gemini API HTTP {exc.code}:\n{body}") from exc
    except URLError as exc:
        raise SystemExit(f"Network error calling Gemini: {exc.reason}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", nargs="?", default=DEFAULT_VIDEO, help="Video URL or local path")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    load_env()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY not found in environment or .env")
    print(f"Using key: {api_key[:6]}…  model: {args.model}\n")

    video_bytes = load_video(args.video)
    encoded = base64.b64encode(video_bytes).decode("ascii")

    url = f"{API_ROOT}/models/{args.model}:generateContent"
    payload = {
        "contents": [
            {
                "parts": [
                    {"inline_data": {"mime_type": "video/mp4", "data": encoded}},
                    {"text": PROMPT},
                ]
            }
        ]
    }

    print("Sending video to Gemini…\n")
    body = post_json(url, api_key, payload)

    candidates = body.get("candidates") or []
    if not candidates:
        raise SystemExit(f"No candidates returned:\n{json.dumps(body, indent=2)}")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()

    print("=" * 70)
    print("GEMINI RESPONSE (proves video was processed):")
    print("=" * 70)
    print(text or "(empty response)")
    print("=" * 70)

    usage = body.get("usageMetadata", {})
    if usage:
        print(
            f"\nTokens — prompt: {usage.get('promptTokenCount')} "
            f"(video counts here), output: {usage.get('candidatesTokenCount')}, "
            f"total: {usage.get('totalTokenCount')}"
        )
    print("\n✅ Gemini accepted and processed the video.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
