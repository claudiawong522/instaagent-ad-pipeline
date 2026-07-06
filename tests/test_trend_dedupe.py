from __future__ import annotations

from instaagent_pipeline.trend_ingest import (
    _dedupe_formats,
    _prune_empty_formats,
    _relink_existing_videos,
    _video_key,
)


class FakeSupabase:
    """Minimal in-memory stand-in supporting the calls the re-link / prune helpers make."""

    def __init__(self, ugc: list[dict], formats: list[dict]) -> None:
        self.ugc = ugc
        self.formats = formats

    def select(self, table, params):
        rows = self.ugc if table == "organic_items" else self.formats
        out = []
        for r in rows:
            ok = True
            for k, v in params.items():
                if k == "select":
                    continue
                col, _, val = v.partition(".")
                if val.startswith("(") and val.endswith(")"):  # in.(a,b)
                    ok = ok and str(r.get(k)) in val[1:-1].split(",")
                elif col == "neq":
                    ok = ok and str(r.get(k)) != val
                else:  # eq
                    ok = ok and str(r.get(k)) == val
            if ok:
                out.append(dict(r))
        return out

    def update_by_id(self, table, row_id, payload):
        for r in self.ugc:
            if str(r["id"]) == str(row_id):
                r.update(payload)
        return {}

    def delete(self, table, params):
        target = params["id"].split(".", 1)[1]
        before = len(self.formats)
        self.formats[:] = [f for f in self.formats if str(f["id"]) != target]
        # emulate ON DELETE CASCADE
        self.ugc[:] = [u for u in self.ugc if str(u.get("format_id")) != target]
        return [{}] * (before - len(self.formats))


def test_video_key_canonicalizes_tiktok_and_ig():
    assert _video_key("https://www.tiktok.com/@a/video/123?is_from_webapp=1") == "tt:123"
    assert _video_key("https://www.tiktok.com/@b/video/123/") == "tt:123"
    assert _video_key("https://instagram.com/reel/AbC123/") == "ig:abc123"


def test_dedupe_merges_formats_sharing_a_video():
    formats = [
        {"format_name": "Hands are full", "format_description": "x",
         "video_urls": ["https://www.tiktok.com/@a/video/7646"]},
        {"format_name": "Sorry I can't", "format_description": "y",
         "video_urls": ["https://www.tiktok.com/@a/video/7646?ref=1"]},
    ]
    out = _dedupe_formats(formats)
    assert len(out) == 1
    assert out[0]["format_name"] == "Hands are full"  # first one wins
    # the sibling's URL is unioned in, still one video after canonicalization
    assert {_video_key(u) for u in out[0]["video_urls"]} == {"tt:7646"}


def test_dedupe_keeps_distinct_formats_and_empty_ones():
    formats = [
        {"format_name": "A", "format_description": "", "video_urls": ["https://www.tiktok.com/@a/video/1"]},
        {"format_name": "B", "format_description": "", "video_urls": ["https://www.tiktok.com/@b/video/2"]},
        {"format_name": "Goals list", "format_description": "", "video_urls": []},
        {"format_name": "No example either", "format_description": "", "video_urls": []},
    ]
    out = _dedupe_formats(formats)
    # distinct videos stay separate; the two no-video formats are both kept (nothing to key on)
    assert [f["format_name"] for f in out] == ["A", "B", "Goals list", "No example either"]


def test_relink_moves_video_to_current_format():
    ugc = [{"id": "u1", "external_id": "7646", "format_id": "old_row", "run_id": "R"}]
    sb = FakeSupabase(ugc, [])
    _relink_existing_videos(sb, "R", {"7646"}, {"7646": "new_row"})
    assert ugc[0]["format_id"] == "new_row"  # followed the current parse


def test_relink_noop_when_already_correct():
    ugc = [{"id": "u1", "external_id": "7646", "format_id": "row", "run_id": "R"}]
    sb = FakeSupabase(ugc, [])
    _relink_existing_videos(sb, "R", {"7646"}, {"7646": "row"})
    assert ugc[0]["format_id"] == "row"


def test_prune_removes_rename_leftover_keeps_video_rows():
    # A rename between renders left "X" empty (its video moved to the fuller-named row); a trend
    # this render simply missed keeps its video. Prune drops only the empty one, and never the
    # missed trend or a different source.
    formats = [
        {"id": "keep", "source_name": "newengen", "format_name": "X Love Me Dance"},
        {"id": "missed", "source_name": "newengen", "format_name": "Missed this render"},
        {"id": "empty", "source_name": "newengen", "format_name": "X"},
        {"id": "other_src", "source_name": "ramdam", "format_name": "Y"},
    ]
    ugc = [
        {"id": "u1", "format_id": "keep", "run_id": "R"},
        {"id": "u2", "format_id": "missed", "run_id": "R"},
    ]
    sb = FakeSupabase(ugc, formats)
    removed = _prune_empty_formats(sb, "newengen")
    assert removed == 1
    assert {f["id"] for f in sb.formats} == {"keep", "missed", "other_src"}


def test_prune_noop_when_all_have_videos():
    formats = [{"id": "a", "source_name": "newengen", "format_name": "A"}]
    ugc = [{"id": "u1", "format_id": "a", "run_id": "R"}]
    sb = FakeSupabase(ugc, formats)
    assert _prune_empty_formats(sb, "newengen") == 0
    assert len(sb.formats) == 1


