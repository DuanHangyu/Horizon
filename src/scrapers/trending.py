"""First-party and specialist GitHub trending source adapters."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, List, Optional
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from ..models import (
    ContentItem,
    GitHubTrendingConfig,
    SourceType,
    TrendshiftConfig,
)
from .base import BaseScraper
from .radar_utils import coerce_int, matches_keywords

logger = logging.getLogger(__name__)


class GitHubTrendingScraper(BaseScraper):
    """Scrape the public GitHub Trending ranking and its daily star signal."""

    BASE_URL = "https://github.com/trending"

    def __init__(self, config: GitHubTrendingConfig, http_client: httpx.AsyncClient):
        super().__init__(config, http_client)
        self.cfg = config

    async def fetch(self, since: datetime) -> List[ContentItem]:
        if not self.cfg.enabled:
            return []

        items_by_repo: dict[str, ContentItem] = {}
        languages = self.cfg.languages or [""]
        for language in languages:
            rows = await self._fetch_language(language)
            for rank, row in enumerate(rows, start=1):
                item = self._row_to_item(row, rank, language)
                if item is None:
                    continue
                repo_key = str(item.metadata["repo"]).lower()
                current = items_by_repo.get(repo_key)
                if current is None:
                    items_by_repo[repo_key] = item
                    continue
                current.metadata["radar_signals"].extend(item.metadata["radar_signals"])
                current.metadata["github_trending_languages"] = sorted(
                    set(current.metadata.get("github_trending_languages", []))
                    | set(item.metadata.get("github_trending_languages", []))
                )

        return list(items_by_repo.values())[: self.cfg.max_items]

    async def _fetch_language(self, language: str) -> list[dict[str, Any]]:
        suffix = f"/{quote(language)}" if language else ""
        try:
            response = await self.client.get(
                f"{self.BASE_URL}{suffix}",
                params={"since": self.cfg.period},
                headers={
                    "Accept": "text/html",
                    "User-Agent": "Mozilla/5.0 Horizon/1.0",
                },
                follow_redirects=True,
                timeout=25.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Error fetching GitHub Trending (%s): %s", language or "all", exc)
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        rows: list[dict[str, Any]] = []
        for article in soup.select("article.Box-row"):
            heading_link = article.select_one("h2 a[href]")
            if heading_link is None:
                continue
            repo = heading_link.get_text(" ", strip=True).replace(" ", "")
            repo = repo.strip("/")
            if repo.count("/") != 1:
                continue

            description_node = article.select_one("p")
            language_node = article.select_one('[itemprop="programmingLanguage"]')
            stars_node = article.select_one(f'a[href="/{repo}/stargazers"]')
            forks_node = article.select_one(f'a[href="/{repo}/forks"]')
            stars_period = 0
            for span in article.select("span"):
                text = span.get_text(" ", strip=True)
                match = re.search(r"([\d,]+)\s+stars?\s+(today|this week|this month)", text, re.I)
                if match:
                    stars_period = coerce_int(match.group(1))
                    break

            rows.append(
                {
                    "repo": repo,
                    "description": (
                        description_node.get_text(" ", strip=True)
                        if description_node is not None
                        else ""
                    ),
                    "language": (
                        language_node.get_text(" ", strip=True)
                        if language_node is not None
                        else language
                    ),
                    "total_stars": coerce_int(
                        stars_node.get_text(" ", strip=True) if stars_node else 0
                    ),
                    "forks": coerce_int(
                        forks_node.get_text(" ", strip=True) if forks_node else 0
                    ),
                    "stars_gained": stars_period,
                }
            )
        return rows

    def _row_to_item(
        self,
        row: dict[str, Any],
        rank: int,
        language_filter: str,
    ) -> Optional[ContentItem]:
        repo = str(row.get("repo") or "")
        description = str(row.get("description") or "")
        if self.cfg.ai_only and not matches_keywords(
            [repo, description], self.cfg.keywords
        ):
            return None

        stars_gained = coerce_int(row.get("stars_gained"))
        signal = {
            "source": "github_trending",
            "rank": rank,
            "period": self.cfg.period,
            "stars_gained": stars_gained,
            "language": language_filter or "all",
        }
        content = (
            f"GitHub Trending rank: #{rank} ({language_filter or 'all'}, {self.cfg.period})\n"
            f"Stars gained: {stars_gained}\n"
            f"Total stars: {row.get('total_stars', 0)}\n"
            f"Forks: {row.get('forks', 0)}\n"
            f"Language: {row.get('language') or 'unknown'}\n\n"
            f"{description}"
        )
        return ContentItem(
            id=self._generate_id("github", "trending", repo.lower()),
            source_type=SourceType.GITHUB,
            title=f"{repo} (+{stars_gained}⭐ {self.cfg.period})",
            url=f"https://github.com/{repo}",
            content=content,
            author=repo.split("/", 1)[0],
            published_at=datetime.now(timezone.utc),
            metadata={
                "repo": repo,
                "category": self.cfg.category,
                "radar_source": "github_trending",
                "radar_signals": [signal],
                "github_trending_rank": rank,
                "github_trending_languages": [language_filter or "all"],
                "stars_gained": stars_gained,
                "stargazers_count": coerce_int(row.get("total_stars")),
                "forks_count": coerce_int(row.get("forks")),
                "primary_language": row.get("language"),
                "description": description,
                "discovery_type": "github_trending",
            },
        )


class TrendshiftScraper(BaseScraper):
    """Fetch Trendshift via its official API, with public-page fallback."""

    API_URL = "https://api.trendshift.io/v1/trending/{period}"
    PAGE_URL = "https://trendshift.io/"

    def __init__(self, config: TrendshiftConfig, http_client: httpx.AsyncClient):
        super().__init__(config, http_client)
        self.cfg = config

    async def fetch(self, since: datetime) -> List[ContentItem]:
        if not self.cfg.enabled:
            return []

        token = os.getenv(self.cfg.api_token_env)
        rows = await self._fetch_api(token) if token else []
        mode = "official_api"
        if not rows:
            rows = await self._fetch_public_page()
            mode = "public_page"

        items: list[ContentItem] = []
        for row in rows[: self.cfg.max_items]:
            item = self._row_to_item(row, mode)
            if item is not None:
                items.append(item)
        return items

    async def _fetch_api(self, token: Optional[str]) -> list[dict[str, Any]]:
        if not token:
            return []
        try:
            response = await self.client.get(
                self.API_URL.format(period=self.cfg.period),
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                params={"limit": self.cfg.max_items},
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
            return payload.get("data") or []
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Error fetching Trendshift API: %s", exc)
            return []

    async def _fetch_public_page(self) -> list[dict[str, Any]]:
        try:
            response = await self.client.get(
                self.PAGE_URL,
                headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0 Horizon/1.0"},
                follow_redirects=True,
                timeout=25.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Error fetching Trendshift public ranking: %s", exc)
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        script = soup.find("script", attrs={"type": "application/ld+json"})
        if script is None or not script.string:
            return []
        try:
            payload = json.loads(script.string)
        except json.JSONDecodeError:
            return []

        rows: list[dict[str, Any]] = []
        for entry in payload.get("itemListElement") or []:
            item = entry.get("item") or {}
            rows.append(
                {
                    "full_name": item.get("name"),
                    "description": item.get("description"),
                    "language": item.get("programmingLanguage"),
                    "created_at": item.get("dateCreated"),
                    "updated_at": item.get("dateModified"),
                    "topics": item.get("keywords") or [],
                    "rank": entry.get("position"),
                    "url": item.get("codeRepository") or item.get("url"),
                }
            )
        return rows

    def _row_to_item(self, row: dict[str, Any], mode: str) -> Optional[ContentItem]:
        repo = str(row.get("full_name") or row.get("repo_name") or "")
        if repo.count("/") != 1:
            return None
        description = str(row.get("description") or "")
        topics = row.get("topics") or row.get("topic_names") or []
        if self.cfg.ai_only and not matches_keywords(
            [repo, description, " ".join(topics)], self.cfg.keywords
        ):
            return None

        rank = coerce_int(row.get("rank")) or None
        stars_gained = coerce_int(row.get("stars_gained"))
        signal = {
            "source": "trendshift",
            "rank": rank,
            "period": self.cfg.period,
            "stars_gained": stars_gained,
            "score": row.get("score"),
            "mode": mode,
        }
        return ContentItem(
            id=self._generate_id("trendshift", "trending", repo.lower()),
            source_type=SourceType.TRENDSHIFT,
            title=f"{repo} (Trendshift #{rank or '?'})",
            url=row.get("url") or f"https://github.com/{repo}",
            content=(
                f"Trendshift rank: #{rank or '?'} ({self.cfg.period})\n"
                f"Stars gained: {stars_gained or 'not exposed'}\n"
                f"Language: {row.get('language') or 'unknown'}\n"
                f"Topics: {', '.join(topics)}\n\n{description}"
            ),
            author=repo.split("/", 1)[0],
            published_at=datetime.now(timezone.utc),
            metadata={
                "repo": repo,
                "category": self.cfg.category,
                "radar_source": "trendshift",
                "radar_signals": [signal],
                "trendshift_rank": rank,
                "stars_gained": stars_gained,
                "stargazers_count": coerce_int(row.get("stars_now")),
                "forks_count": coerce_int(row.get("forks_now")),
                "primary_language": row.get("language"),
                "topics": topics,
                "description": description,
                "discovery_type": "trendshift_ranking",
            },
        )
