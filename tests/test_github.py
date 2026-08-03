import asyncio
from datetime import datetime, timezone

import httpx

from src.models import GitHubSourceConfig
from src.scrapers.github import GitHubScraper


def test_repo_search_discovers_recent_ai_repositories(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search/repositories"
        assert "topic%3Allm" in str(request.url)
        assert "stars%3A%3E%3D20" in str(request.url)
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": 123,
                        "full_name": "example/agent-kit",
                        "html_url": "https://github.com/example/agent-kit",
                        "description": "Build production AI agents",
                        "created_at": "2026-07-20T08:00:00Z",
                        "pushed_at": "2026-08-03T01:00:00Z",
                        "stargazers_count": 420,
                        "forks_count": 31,
                        "open_issues_count": 4,
                        "language": "Python",
                        "topics": ["llm", "agents"],
                        "license": {"spdx_id": "Apache-2.0"},
                        "owner": {"login": "example"},
                        "homepage": "https://example.com/agent-kit",
                    }
                ]
            },
        )

    source = GitHubSourceConfig(
        type="repo_search",
        query="topic:llm",
        lookback_days=30,
        min_stars=20,
        max_items=15,
        category="github-trending",
    )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            scraper = GitHubScraper([source], client)
            return await scraper.fetch(datetime(2026, 8, 1, tzinfo=timezone.utc))

    items = asyncio.run(run())

    assert len(items) == 1
    assert items[0].id == "github:repo:123"
    assert items[0].metadata["category"] == "github-trending"
    assert items[0].metadata["stargazers_count"] == 420
    assert items[0].metadata["license"] == "Apache-2.0"
    assert "Stars: 420" in (items[0].content or "")
