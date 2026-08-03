from types import SimpleNamespace

from src.models import OSSInsightConfig
from src.scrapers.ossinsight import OSSInsightScraper


def test_short_ai_keyword_matches_whole_token_only():
    scraper = OSSInsightScraper(
        OSSInsightConfig(enabled=True, keywords=["ai"]),
        SimpleNamespace(),
    )

    assert scraper._matches_keywords({"description": "An AI coding agent"}) is True
    assert scraper._matches_keywords({"description": "A maintainable web framework"}) is False


def test_ossinsight_items_receive_configured_digest_category():
    scraper = OSSInsightScraper(
        OSSInsightConfig(enabled=True, category="github-trending"),
        SimpleNamespace(),
    )

    item = scraper._row_to_item(
        {
            "repo_id": 42,
            "repo_name": "example/ai-tool",
            "stars": 100,
            "description": "An AI tool",
            "primary_language": "Python",
        },
        "Python",
    )

    assert item is not None
    assert item.metadata["category"] == "github-trending"
    assert item.metadata["discovery_type"] == "star_velocity"
