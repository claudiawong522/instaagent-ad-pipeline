from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

import instaagent_pipeline.cli as cli
from instaagent_pipeline.cli import to_jsonable
from instaagent_pipeline.ingestion import IngestResult


def test_to_jsonable_converts_nested_dataclasses() -> None:
    @dataclass
    class Result:
        written: int

    assert to_jsonable({"transcripts": {"apify": Result(written=2)}}) == {
        "transcripts": {"apify": {"written": 2}}
    }


def test_ingest_apify_ads_triggers_enrichment(monkeypatch: Any, capsys: Any) -> None:
    calls: dict[str, Any] = {}

    monkeypatch.setattr(cli, "build_supabase", lambda config, dry_run: object())
    monkeypatch.setattr(
        cli,
        "ingest_apify_ads",
        lambda **kwargs: IngestResult(fetched=3, written=3),
    )

    def fake_enrich(**kwargs: Any) -> dict[str, Any]:
        calls["enrich"] = kwargs
        return {"written": 3}

    monkeypatch.setattr(cli, "enrich_paid_ads", fake_enrich)

    exit_code = cli.main(
        ["ingest-apify-ads", "--run-id", "run_1", "--keyword", "cleanser"]
    )

    assert exit_code == 0
    assert calls["enrich"]["run_id"] == "run_1"
    assert calls["enrich"]["limit"] == 3
    output = capsys.readouterr().out
    assert '"enrichment"' in output


def test_ingest_apify_ads_skip_enrichment(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setattr(cli, "build_supabase", lambda config, dry_run: object())
    monkeypatch.setattr(
        cli,
        "ingest_apify_ads",
        lambda **kwargs: IngestResult(fetched=3, written=3),
    )

    def fail_enrich(**kwargs: Any) -> None:
        raise AssertionError("enrich_paid_ads should not be called with --skip-enrichment")

    monkeypatch.setattr(cli, "enrich_paid_ads", fail_enrich)

    exit_code = cli.main(
        ["ingest-apify-ads", "--run-id", "run_1", "--keyword", "cleanser", "--skip-enrichment"]
    )

    assert exit_code == 0
    assert '"enrichment"' not in capsys.readouterr().out


def test_enrich_paid_ads_command_dispatches(monkeypatch: Any, capsys: Any) -> None:
    calls: dict[str, Any] = {}

    monkeypatch.setattr(cli, "build_supabase", lambda config, dry_run: object())

    def fake_enrich(**kwargs: Any) -> dict[str, Any]:
        calls["enrich"] = kwargs
        return {"written": 1}

    monkeypatch.setattr(cli, "enrich_paid_ads", fake_enrich)

    exit_code = cli.main(["enrich-paid-ads", "--run-id", "run_1", "--limit", "5"])

    assert exit_code == 0
    assert calls["enrich"]["run_id"] == "run_1"
    assert calls["enrich"]["limit"] == 5
    assert calls["enrich"]["timeout"] == 300


@pytest.mark.parametrize("command", ["ingest-tiktok", "ingest-instagram"])
def test_ingest_organic_triggers_enrichment(
    command: str, monkeypatch: Any, capsys: Any
) -> None:
    calls: dict[str, Any] = {}

    monkeypatch.setattr(cli, "build_supabase", lambda config, dry_run: object())
    monkeypatch.setattr(cli, "ingest_tiktok", lambda **kwargs: IngestResult(fetched=4, written=4))
    monkeypatch.setattr(cli, "ingest_instagram", lambda **kwargs: IngestResult(fetched=4, written=4))

    def fake_enrich(**kwargs: Any) -> dict[str, Any]:
        calls["enrich"] = kwargs
        return {"written": 4}

    monkeypatch.setattr(cli, "enrich_organic_items", fake_enrich)

    exit_code = cli.main([command, "--run-id", "run_1", "--keyword", "cleanser"])

    assert exit_code == 0
    assert calls["enrich"]["run_id"] == "run_1"
    assert calls["enrich"]["limit"] == 4
    assert calls["enrich"]["timeout"] == 300
    output = capsys.readouterr().out
    assert '"enrichment"' in output


@pytest.mark.parametrize("command", ["ingest-tiktok", "ingest-instagram"])
def test_ingest_organic_skip_enrichment(
    command: str, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.setattr(cli, "build_supabase", lambda config, dry_run: object())
    monkeypatch.setattr(cli, "ingest_tiktok", lambda **kwargs: IngestResult(fetched=4, written=4))
    monkeypatch.setattr(cli, "ingest_instagram", lambda **kwargs: IngestResult(fetched=4, written=4))

    def fail_enrich(**kwargs: Any) -> None:
        raise AssertionError("enrich_organic_items should not be called with --skip-enrichment")

    monkeypatch.setattr(cli, "enrich_organic_items", fail_enrich)

    exit_code = cli.main(
        [command, "--run-id", "run_1", "--keyword", "cleanser", "--skip-enrichment"]
    )

    assert exit_code == 0
    assert '"enrichment"' not in capsys.readouterr().out


def test_embed_items_accepts_new_spaces() -> None:
    parser = cli.build_parser()
    for space in ("icp", "search", "all"):
        args = parser.parse_args(["embed-items", "--run-id", "run_1", "--space", space])
        assert args.space == space


@pytest.mark.parametrize("space", ["format", "hook"])
def test_embed_items_rejects_removed_spaces(space: str) -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["embed-items", "--run-id", "run_1", "--space", space])
