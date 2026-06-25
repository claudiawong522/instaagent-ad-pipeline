from __future__ import annotations

from instaagent_pipeline.audience_enrichment import CONTENT_FORMATS, _normalize


def test_normalize_coerces_content_formats_to_vocab() -> None:
    analysis = {
        "target_generation": "genz",
        "price_positioning": "budget",
        "age_brackets": ["18-24"],
        "languages": ["english"],
        # Mixed case + a junk value that must be dropped; overlap is allowed.
        "content_formats": ["TalkingHead_junk", "Meme", "ugc", "ugc"],
    }
    out = _normalize(analysis)
    # Junk dropped, valid values lowercased, deduped, order preserved.
    assert out["content_formats"] == ["meme", "ugc"]


def test_normalize_content_formats_defaults_to_empty_list() -> None:
    out = _normalize({"content_formats": None})
    assert out["content_formats"] == []
    out = _normalize({})
    assert out["content_formats"] == []


def test_content_formats_vocab_is_the_core_13() -> None:
    assert len(CONTENT_FORMATS) == 13
    assert "product_montage" in CONTENT_FORMATS
    assert "grwm" in CONTENT_FORMATS
