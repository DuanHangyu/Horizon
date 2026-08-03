import asyncio
from datetime import datetime, timezone

import httpx

from src.models import (
    HuggingFaceSpacesConfig,
    ProductHuntConfig,
    YCProductsConfig,
)
from src.scrapers.product_radar import (
    HuggingFaceSpacesScraper,
    ProductHuntScraper,
    YCProductsScraper,
)


def test_product_hunt_rss_fallback_filters_by_published_time(monkeypatch) -> None:
    monkeypatch.delenv("PRODUCTHUNT_TOKEN", raising=False)
    feed = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
      <entry><id>tag:producthunt.com,2005:Post/42</id>
        <published>2026-08-03T01:00:00Z</published>
        <link href="https://www.producthunt.com/products/agent-kit"/>
        <title>Agent Kit</title><content type="html">&lt;p&gt;AI workflow product&lt;/p&gt;</content>
        <author><name>Alice</name></author></entry>
      <entry><id>tag:producthunt.com,2005:Post/41</id>
        <published>2026-07-01T01:00:00Z</published>
        <link href="https://www.producthunt.com/products/old"/>
        <title>Old</title><content type="html">&lt;p&gt;Old&lt;/p&gt;</content></entry>
    </feed>"""

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=feed))
        ) as client:
            return await ProductHuntScraper(
                ProductHuntConfig(enabled=True), client
            ).fetch(datetime(2026, 8, 2, tzinfo=timezone.utc))

    items = asyncio.run(run())
    assert [item.title for item in items] == ["Agent Kit"]
    assert items[0].metadata["radar_source"] == "producthunt"
    assert items[0].metadata["api_metrics_available"] is False


def test_yc_launches_uses_ai_directory_and_launch_metrics() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/companies/industry/ai":
            return httpx.Response(200, text='<a href="/companies/acme">Acme</a>')
        return httpx.Response(
            200,
            json={
                "hits": [
                    {
                        "id": 7,
                        "title": "Acme launches a workflow tool",
                        "tagline": "Automates enterprise work",
                        "created_at": "2026-08-03T01:00:00Z",
                        "total_vote_count": 33,
                        "search_path": "https://www.ycombinator.com/launches/acme",
                        "company": {
                            "name": "Acme",
                            "slug": "acme",
                            "tags": ["B2B"],
                            "batch": "S2026",
                        },
                    }
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await YCProductsScraper(
                YCProductsConfig(enabled=True), client
            ).fetch(datetime(2026, 8, 2, tzinfo=timezone.utc))

    items = asyncio.run(run())
    assert len(items) == 1
    assert items[0].metadata["yc_ai_directory_match"] is True
    assert items[0].metadata["votes"] == 33


def test_huggingface_spaces_requires_recent_liked_public_space() -> None:
    rows = [
        {
            "id": "acme/agent-demo",
            "private": False,
            "likes": 120,
            "createdAt": "2026-08-03T00:00:00Z",
            "sdk": "gradio",
            "tags": ["agents"],
            "cardData": {"title": "Agent Demo", "short_description": "Try an AI agent"},
        },
        {"id": "acme/private", "private": True, "likes": 999},
    ]

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=rows))
        ) as client:
            return await HuggingFaceSpacesScraper(
                HuggingFaceSpacesConfig(enabled=True, min_likes=10), client
            ).fetch(datetime(2026, 8, 2, tzinfo=timezone.utc))

    items = asyncio.run(run())
    assert len(items) == 1
    assert items[0].metadata["huggingface_rank"] == 1
    assert items[0].metadata["likes"] == 120
