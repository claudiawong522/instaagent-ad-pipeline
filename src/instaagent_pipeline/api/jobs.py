"""Background scrape-job plumbing shared by the campaign and discover workers.

Owns the process-local running-job registry, the per-run post-pass serialization locks,
the scrape_events open/close bookkeeping (cost reconcile + out-of-credits detection),
and the hung-worker watchdog — the skeleton that campaigns._run_scrape and
discover._run_discovery used to each hand-roll.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from ..config import Config
from ..costs import detect_out_of_credits, reconcile_actual_cost
from ..ingestion import utc_now_iso
from ..supabase_client import SupabaseClient

# Scrapes currently running, so the UI can show a spinner and we refuse duplicates. Keyed
# by (run_id, platform). Process-local — fine for the single-worker dev server; a
# multi-worker deploy would track this in the DB instead.
_running: set[tuple[str, str]] = set()
_running_lock = threading.Lock()

# Backstop for a worker that hangs *after* fetching (e.g. a stalled vision/embed call): if its
# event sits in 'running' this long, mark it failed so the UI stops spinning forever and offers a
# re-run, and free the running slot. Sized above a full first post-pass, not a tight SLA — the
# run-wide passes are serialized and skip already-done items, so only one worker pays full cost.
WATCHDOG_SECONDS = 30 * 60

# The post-ingest passes (organic enrich, audience, embed) all cover a run's WHOLE item set, not
# just one scrape's. With several platform workers live at once, running them in parallel just makes
# N workers hammer the same rate-limited vision/embed APIs and crawl — which is what leaves an event
# stuck 'running' long after its fetch is done. Serialize them per run: one lock per run_id, lazily
# created under a guard. Apify ingest stays parallel; only post-processing is single-file.
_postpass_locks: dict[str, threading.Lock] = {}
_postpass_guard = threading.Lock()


def postpass_lock(run_id: str) -> threading.Lock:
    with _postpass_guard:
        lock = _postpass_locks.get(run_id)
        if lock is None:
            lock = threading.Lock()
            _postpass_locks[run_id] = lock
        return lock


def try_claim(run_id: str, platform: str) -> bool:
    """Reserve the (run_id, platform) slot; False if that scrape is already running."""
    with _running_lock:
        if (run_id, platform) in _running:
            return False
        _running.add((run_id, platform))
        return True


def release(run_id: str, platform: str) -> None:
    with _running_lock:
        _running.discard((run_id, platform))


def running_platforms(run_id: str) -> list[str]:
    with _running_lock:
        return sorted(p for (r, p) in _running if r == run_id)


def live_keys() -> set[tuple[str, str]]:
    with _running_lock:
        return set(_running)


@dataclass
class JobState:
    """What a job's work callback reports back for the scrape_events close-out. Filled in
    as the work proceeds so a mid-work exception still closes the event with the items
    ingested so far."""

    items_ingested: int = 0
    # True when the job finished but delivered short (e.g. one keyword's ingest errored),
    # so the event is flagged failed and the UI offers a retry.
    partial_failure: bool = False


def run_job(
    *,
    config: Config,
    run_id: str,
    platform: str,
    target_count: int | None,
    estimate: float | None,
    work: Callable[[SupabaseClient, JobState], None],
    watchdog_seconds: int | None = None,
    log_prefix: str = "scrape",
) -> None:
    """Run one background scrape job with full scrape_events bookkeeping.

    Opens the event, arms the optional watchdog, runs `work`, then in all cases closes
    the event (real-cost reconcile + out-of-credits detection) and frees the running
    slot. `work` gets a thread-fresh SupabaseClient and the JobState to fill in."""
    # Fresh client for the thread — don't share the request handler's session across threads.
    supabase = SupabaseClient(config.supabase_url, config.supabase_key)
    # Record the scrape so the UI can show its cost. Best-effort — cost bookkeeping must
    # never block the scrape (e.g. if migration 022 hasn't been applied yet).
    event_id: str | None = None
    started_at: str | None = None
    try:
        event = supabase.insert(
            "scrape_events",
            {"run_id": run_id, "platform": platform, "target_count": target_count, "estimated_cost_usd": estimate},
        )
        event_id, started_at = event.get("id"), event.get("started_at")
    except Exception as exc:
        print(f"[{log_prefix}] run={run_id} could not record scrape_event: {exc}")

    # Backstop a hung worker: if we never reach the finally below in time, this fires and closes
    # the event (see _watchdog_timeout). Cancelled the moment the worker finishes normally.
    watchdog: threading.Timer | None = None
    if watchdog_seconds and event_id:
        watchdog = threading.Timer(
            watchdog_seconds, _watchdog_timeout, args=(config, run_id, platform, str(event_id), log_prefix)
        )
        watchdog.daemon = True
        watchdog.start()

    state = JobState()
    failed = False
    try:
        work(supabase, state)
    except Exception as exc:  # background thread — surface to the server log, nothing to return to
        failed = True
        print(f"[{log_prefix}] run={run_id} platform={platform} failed: {exc}")
    finally:
        # Worker finished (or errored) on its own — call off the backstop before it can fire.
        if watchdog is not None:
            watchdog.cancel()
        # Reconcile the real spend (Apify USD + token-priced LLM/embeds) for this scrape's window.
        if event_id:
            try:
                actual = reconcile_actual_cost(supabase, run_id, started_at) if started_at else None
                # Did either leg (Apify ingest / LLM enrichment) run out of credits? Detected from
                # the run's failed source_queries so the UI can prompt a top-up + re-run. Set even
                # when status is 'done' (an enrichment credit failure is swallowed per item).
                credit_error = detect_out_of_credits(supabase, run_id, started_at) if started_at else None
                supabase.update_by_id(
                    "scrape_events",
                    str(event_id),
                    {
                        "actual_cost_usd": actual,
                        "items_ingested": state.items_ingested,
                        "status": "failed" if (failed or state.partial_failure) else "done",
                        "error_message": credit_error,
                        "finished_at": utc_now_iso(),
                    },
                )
            except Exception as exc:  # never let cost bookkeeping mask the scrape outcome
                print(f"[{log_prefix}] run={run_id} cost reconcile failed: {exc}")
        release(run_id, platform)


def _watchdog_timeout(config: Config, run_id: str, platform: str, event_id: str, log_prefix: str) -> None:
    """Fired by a Timer if a worker overruns the watchdog. Flips a still-'running' event to
    failed (so the UI offers a re-run instead of spinning forever) and frees the running slot.
    No-op if the worker already closed the event — the worker cancels this Timer in its finally,
    so this only runs when the worker is genuinely stuck and never reached that finally."""
    supabase = SupabaseClient(config.supabase_url, config.supabase_key)
    try:
        rows = supabase.select("scrape_events", {"select": "status", "id": f"eq.{event_id}", "limit": "1"})
        if rows and rows[0].get("status") == "running":
            supabase.update_by_id(
                "scrape_events",
                event_id,
                {
                    "status": "failed",
                    "error_message": "Scrape timed out — the worker stalled. Re-run to finish.",
                    "finished_at": utc_now_iso(),
                },
            )
            print(f"[{log_prefix}] run={run_id} platform={platform} watchdog: stalled scrape marked failed")
    except Exception as exc:
        print(f"[{log_prefix}] run={run_id} watchdog update failed: {exc}")
    release(run_id, platform)
