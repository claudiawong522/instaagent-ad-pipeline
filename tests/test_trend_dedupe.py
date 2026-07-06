from __future__ import annotations

from instaagent_pipeline.trend_ingest import (
    _dedupe_formats,
    _prune_stale_formats,
    _relink_existing_videos,
    _video_key,
)


class FakeSupabase:
    """Minimal in-memory stand-in supporting the calls the re-link / prune helpers make."""

    def __init__(self, ugc: list[dict], formats: list[dict]) -> None:
        self.ugc = ugc
        self.formats = formats

    def select(self, table, params):
        rows = self.ugc if table == "ugc_items" else self.formats
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


def test_prune_drops_only_old_page_version_rows():
    formats = [
        {"id": "cur1", "source_name": "socialbee", "content_hash": "H2"},
        {"id": "old1", "source_name": "socialbee", "content_hash": "H1"},  # stale, empty after relink
        {"id": "old2", "source_name": "socialbee", "content_hash": "H1"},  # trend dropped from page
    ]
    ugc = [{"id": "u2", "external_id": "999", "format_id": "old2", "run_id": "R"}]  # cascades away
    sb = FakeSupabase(ugc, formats)
    removed = _prune_stale_formats(sb, "socialbee", "H2")
    assert removed == 2
    assert [f["id"] for f in formats] == ["cur1"]
    assert ugc == []  # cascade deleted the orphaned video
