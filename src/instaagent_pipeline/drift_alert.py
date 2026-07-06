"""Parser-drift email alert for the trend ingest.

When a trend source's page/newsletter layout changes, its parser stops working as
intended — either loudly (fetch/parse raises, zero video links found) or silently
(the structural parser no longer recognizes the page and the run falls back to the
LLM). This module turns those signals from an ingest run into one reminder email to
the owner so the parser gets fixed by hand.

Sending is free: plain Gmail SMTP with an app password (no paid email service).
Env vars: ALERT_SMTP_USER + ALERT_SMTP_PASSWORD (Gmail address + app password from
https://myaccount.google.com/apppasswords), optional ALERT_EMAIL_TO (defaults to
instaagenttool@gmail.com). With no creds set, the alert is logged instead of sent —
an ingest run never fails because of the alert.

Preview the email without sending:  python -m instaagent_pipeline.drift_alert
Send a real test email:             python -m instaagent_pipeline.drift_alert --send
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Any

from .config import Config

logger = logging.getLogger(__name__)

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 465  # SSL


def drift_signals(
    source_results: list[dict[str, Any]], *, llm_expected: set[str] | None = None
) -> list[dict[str, str]]:
    """[{source, reason}] for each source whose parser looks broken by a page change.

    Signals (from the per-source ingest results, nothing re-fetched):
    - status "failed": the fetch or parse raised (e.g. SGE sitemap slug renamed, gate changed).
    - status "no_linked_formats": formats parsed but zero example-video links — the page's
      embed/link markup likely moved.
    - parse_method "llm" on a source whose intended path is structural: the numbered/heading
      parser no longer recognizes the page, i.e. a redesign. llm_expected names the sources
      (SGE) where the LLM parse IS the intended path, so falling to it is not drift.

    Transient statuses (incomplete_render, unchanged) are deliberately not signals.
    """
    llm_expected = llm_expected or set()
    signals: list[dict[str, str]] = []
    for sr in source_results:
        name = str(sr.get("source_name") or "?")
        status = sr.get("status")
        if status == "failed":
            signals.append(
                {"source": name, "reason": f"Fetch/parse failed outright: {sr.get('error')}"}
            )
        elif status == "no_linked_formats":
            signals.append(
                {
                    "source": name,
                    "reason": (
                        "Parse found formats but none had an example-video link — the page's "
                        "video embeds/links likely moved in a redesign."
                    ),
                }
            )
        elif sr.get("parse_method") == "llm" and name not in llm_expected:
            signals.append(
                {
                    "source": name,
                    "reason": (
                        "Structural parser no longer recognizes the page (fell back to the LLM "
                        "parse) — a redesign likely moved the trend headings/numbering."
                    ),
                }
            )
    return signals


def render_drift_email(signals: list[dict[str, str]], to_addr: str) -> tuple[str, str]:
    """(subject, plain-text body) for the reminder email."""
    names = ", ".join(s["source"] for s in signals)
    subject = f"[InstaAgent] Trend parser needs a manual fix: {names}"
    lines = [
        "Hi,",
        "",
        f"The scheduled trend ingest detected that {len(signals)} source"
        f"{'s' if len(signals) != 1 else ''} changed layout, so the parser is no longer "
        "working as intended:",
        "",
    ]
    for s in signals:
        lines += [f"  * {s['source']}", f"    {s['reason']}", ""]
    lines += [
        "What to do:",
        "  1. Open the source page and compare it against the parser assumptions in",
        "     src/instaagent_pipeline/trend_sources.py (segment_numbered_page /",
        "     segment_headed_page, or the SGE fetch helpers).",
        "  2. Reproduce locally: LIVE_TREND_TESTS=1 pytest tests/test_live_trend_pages.py",
        "  3. Fix the parser, then re-run:",
        "     python -m instaagent_pipeline.cli ingest-trends --source-name <source> --force",
        "",
        "This alert re-checks on every scheduled run and will email again until the",
        "parser is fixed. (Sent by instaagent_pipeline/drift_alert.py via Gmail SMTP.)",
    ]
    return subject, "\n".join(lines)


def maybe_send_drift_alert(
    config: Config,
    source_results: list[dict[str, Any]],
    *,
    llm_expected: set[str] | None = None,
) -> dict[str, Any] | None:
    """Detect drift in an ingest run's per-source results and email the owner. Best-effort:
    returns a small summary dict (or None when nothing drifted); never raises."""
    signals = drift_signals(source_results, llm_expected=llm_expected)
    if not signals:
        return None
    subject, body = render_drift_email(signals, config.alert_email_to)
    if not (config.alert_smtp_user and config.alert_smtp_password):
        logger.warning(
            "Parser drift detected but ALERT_SMTP_USER/ALERT_SMTP_PASSWORD are not set; "
            "alert not emailed.\n%s\n\n%s", subject, body,
        )
        return {"signals": signals, "emailed": False, "reason": "smtp creds not configured"}
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = config.alert_smtp_user
        msg["To"] = config.alert_email_to
        msg.set_content(body)
        with smtplib.SMTP_SSL(_SMTP_HOST, _SMTP_PORT, timeout=30) as smtp:
            smtp.login(config.alert_smtp_user, config.alert_smtp_password)
            smtp.send_message(msg)
        logger.info("Drift alert emailed to %s (%d source(s)).", config.alert_email_to, len(signals))
        return {"signals": signals, "emailed": True}
    except Exception as exc:  # the alert must never sink the ingest itself
        logger.warning("Drift alert email failed: %s", exc)
        return {"signals": signals, "emailed": False, "reason": str(exc)[:200]}


_SAMPLE_SIGNALS = [
    {
        "source": "socialbee",
        "reason": (
            "Structural parser no longer recognizes the page (fell back to the LLM parse) — "
            "a redesign likely moved the trend headings/numbering."
        ),
    },
    {
        "source": "socialgrowthengineers",
        "reason": (
            "Fetch/parse failed outright: No SGE 'viral hits' post found in sitemap."
        ),
    },
]


if __name__ == "__main__":
    import sys

    config = Config.from_env()
    subject, body = render_drift_email(_SAMPLE_SIGNALS, config.alert_email_to)
    if "--send" in sys.argv:
        summary = maybe_send_drift_alert(
            config,
            [{"source_name": s["source"],
              "status": "failed" if "failed" in s["reason"] else "parsed",
              "error": s["reason"], "parse_method": "llm"} for s in _SAMPLE_SIGNALS],
        )
        print(summary)
    else:
        print(f"To:      {config.alert_email_to}")
        print(f"From:    {config.alert_smtp_user or '(ALERT_SMTP_USER not set)'}")
        print(f"Subject: {subject}")
        print()
        print(body)
