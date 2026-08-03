import asyncio
from datetime import datetime, timezone

import httpx

from src.models import ShowHNConfig
from src.scrapers.hackernews import ShowHNScraper


def test_show_hn_uses_official_story_list_and_adds_product_signal() -> None:
    now = int(datetime(2026, 8, 3, 1, tzinfo=timezone.utc).timestamp())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/showstories.json"):
            return httpx.Response(200, json=[101])
        if request.url.path.endswith("/item/101.json"):
            return httpx.Response(
                200,
                json={
                    "id": 101,
                    "type": "story",
                    "by": "alice",
                    "time": now,
                    "title": "Show HN: AI workflow debugger",
                    "url": "https://example.com/debugger",
                    "score": 55,
                    "descendants": 12,
                    "kids": [],
                },
            )
        raise AssertionError(request.url)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await ShowHNScraper(
                ShowHNConfig(enabled=True, min_score=10), client
            ).fetch(datetime(2026, 8, 2, tzinfo=timezone.utc))

    items = asyncio.run(run())
    assert len(items) == 1
    assert items[0].metadata["radar_source"] == "show_hn"
    assert items[0].metadata["radar_signals"][0]["points"] == 55
