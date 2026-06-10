from __future__ import annotations

from dataclasses import dataclass

from instaagent_pipeline.cli import to_jsonable


def test_to_jsonable_converts_nested_dataclasses() -> None:
    @dataclass
    class Result:
        written: int

    assert to_jsonable({"transcripts": {"apify": Result(written=2)}}) == {
        "transcripts": {"apify": {"written": 2}}
    }
