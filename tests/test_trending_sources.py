import asyncio
from datetime import datetime, timezone

import httpx

from src.models import GitHubTrendingConfig, TrendshiftConfig
from src.scrapers.trending import GitHubTrendingScraper, TrendshiftScraper


def test_github_trending_extracts_rank_and_daily_stars() -> None:
    html = """
    <article class="Box-row">
      <h2><a href="/acme/agent-kit">acme / agent-kit</a></h2>
      <p>Production AI agent framework</p>
      <span itemprop="programmingLanguage">Python</span>
      <a href="/acme/agent-kit/stargazers">12,345</a>
      <a href="/acme/agent-kit/forks">456</a>
      <span>321 stars today</span>
    </article>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/trending"
        return httpx.Response(200, text=html)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await GitHubTrendingScraper(
                GitHubTrendingConfig(enabled=True), client
            ).fetch(datetime(2026, 8, 2, tzinfo=timezone.utc))

    items = asyncio.run(run())
    assert len(items) == 1
    assert items[0].metadata["github_trending_rank"] == 1
    assert items[0].metadata["stars_gained"] == 321
    assert items[0].metadata["radar_signals"][0]["source"] == "github_trending"


def test_trendshift_public_page_fallback_reads_json_ld(monkeypatch) -> None:
    monkeypatch.delenv("TRENDSHIFT_API_TOKEN", raising=False)
    html = """
    <script type="application/ld+json">
    {"itemListElement":[{"position":2,"item":{
      "name":"acme/ai-demo","description":"AI demo app",
      "codeRepository":"https://github.com/acme/ai-demo",
      "programmingLanguage":"TypeScript","keywords":["AI agent"]}}]}
    </script>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await TrendshiftScraper(
                TrendshiftConfig(enabled=True), client
            ).fetch(datetime(2026, 8, 2, tzinfo=timezone.utc))

    items = asyncio.run(run())
    assert len(items) == 1
    assert items[0].metadata["trendshift_rank"] == 2
    assert items[0].metadata["radar_signals"][0]["mode"] == "public_page"
