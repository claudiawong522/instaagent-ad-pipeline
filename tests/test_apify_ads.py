from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from instaagent_pipeline.apify_ads import apify_ad_items, apify_ads_actor_input, build_meta_ad_library_url


def test_build_meta_ad_library_url_uses_keyword_and_all_countries() -> None:
    url = build_meta_ad_library_url("gentle cleanser")
    query = parse_qs(urlparse(url).query)

    assert query["q"] == ["gentle cleanser"]
    assert query["country"] == ["ALL"]
    assert query["is_targeted_country"] == ["false"]
    assert query["media_type"] == ["video"]
    assert query["publisher_platforms[0]"] == ["instagram"]
    assert query["publisher_platforms[1]"] == ["facebook"]
    assert query["search_type"] == ["keyword_unordered"]


def test_apify_ads_actor_input_wraps_meta_ad_library_url() -> None:
    actor_input = apify_ads_actor_input(
        meta_ad_library_url="https://www.facebook.com/ads/library/?search_terms=gentle+cleanser",
        target_count=25,
    )

    assert actor_input == {
        "startUrls": [{"url": "https://www.facebook.com/ads/library/?search_terms=gentle+cleanser"}],
        "resultsLimit": 25,
        "activeStatus": "",
        "onlyTotal": False,
        "includeAboutPage": False,
        "isDetailsPerAd": False,
    }


def test_apify_ad_items_filters_diagnostic_rows() -> None:
    items = apify_ad_items(
        [
            {
                "url": "https://www.facebook.com/ads/library/?search_terms=cleanser",
                "error": "no_items",
                "errorDescription": "Empty or private data for provided input",
            },
            {"adArchiveID": "123", "pageName": "Example brand"},
        ],
    )

    assert items == [{"adArchiveID": "123", "pageName": "Example brand"}]
