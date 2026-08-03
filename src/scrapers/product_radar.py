"""High-signal AI product launch and demo source adapters."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

import feedparser
import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from ..models import (
    ContentItem,
    DEFAULT_AI_RADAR_KEYWORDS,
    HuggingFaceSpacesConfig,
    ProductHuntConfig,
    SourceType,
    YCProductsConfig,
)
from .base import BaseScraper
from .radar_utils import coerce_int, matches_keywords

logger = logging.getLogger(__name__)


def _parse_datetime(value: object) -> Optional[datetime]:
    if not value:
        return None
    try:
        result = date_parser.parse(str(value))
    except (TypeError, ValueError, OverflowError):
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


class ProductHuntScraper(BaseScraper):
    """Fetch Product Hunt GraphQL launches, falling back to its public feed."""

    GRAPHQL_URL = "https://api.producthunt.com/v2/api/graphql"

    def __init__(self, config: ProductHuntConfig, http_client: httpx.AsyncClient):
        super().__init__(config, http_client)
        self.cfg = config

    async def fetch(self, since: datetime) -> List[ContentItem]:
        if not self.cfg.enabled:
            return []
        token = os.getenv(self.cfg.api_token_env)
        if token:
            rows = await self._fetch_graphql(token, since)
            if rows:
                return [
                    item
                    for rank, row in enumerate(rows, start=1)
                    if (item := self._graphql_row_to_item(row, rank, since)) is not None
                ][: self.cfg.max_items]
        return await self._fetch_feed(since)

    async def _fetch_graphql(self, token: str, since: datetime) -> list[dict[str, Any]]:
        query = """
        query HorizonDailyProducts($first: Int!, $postedAfter: DateTime!) {
          posts(first: $first, postedAfter: $postedAfter, order: RANKING) {
            nodes {
              id name tagline description createdAt featuredAt
              votesCount commentsCount dailyRank url website
              makers { name username }
              topics { nodes { name slug } }
            }
          }
        }
        """
        try:
            response = await self.client.post(
                self.GRAPHQL_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "variables": {
                        "first": self.cfg.max_items,
                        "postedAfter": since.isoformat(),
                    },
                },
                timeout=25.0,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("errors"):
                logger.warning("Product Hunt GraphQL returned errors: %s", payload["errors"])
                return []
            return (((payload.get("data") or {}).get("posts") or {}).get("nodes") or [])
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Error fetching Product Hunt GraphQL: %s", exc)
            return []

    def _graphql_row_to_item(
        self,
        row: dict[str, Any],
        fallback_rank: int,
        since: datetime,
    ) -> Optional[ContentItem]:
        published_at = _parse_datetime(row.get("createdAt"))
        if published_at is None or published_at < since:
            return None
        name = str(row.get("name") or "").strip()
        url = row.get("url") or row.get("website")
        if not name or not url:
            return None
        topics = [node.get("name") for node in ((row.get("topics") or {}).get("nodes") or [])]
        if self.cfg.ai_only and not matches_keywords(
            [
                name,
                row.get("tagline"),
                row.get("description"),
                " ".join(topic for topic in topics if topic),
            ],
            self.cfg.keywords,
        ):
            return None
        makers = [node.get("name") for node in row.get("makers") or [] if node.get("name")]
        votes = coerce_int(row.get("votesCount"))
        comments = coerce_int(row.get("commentsCount"))
        rank = coerce_int(row.get("dailyRank")) or fallback_rank
        return ContentItem(
            id=self._generate_id("producthunt", "post", str(row.get("id") or name)),
            source_type=SourceType.PRODUCTHUNT,
            title=name,
            url=url,
            content=(
                f"{row.get('tagline') or ''}\n\n{row.get('description') or ''}\n\n"
                f"Product Hunt daily rank: #{rank}\nVotes: {votes}\nComments: {comments}\n"
                f"Topics: {', '.join(topic for topic in topics if topic)}"
            ),
            author=", ".join(makers) or None,
            published_at=published_at,
            metadata={
                "category": self.cfg.category,
                "radar_source": "producthunt",
                "radar_signals": [
                    {
                        "source": "producthunt",
                        "rank": rank,
                        "votes": votes,
                        "comments": comments,
                        "mode": "official_api",
                    }
                ],
                "producthunt_rank": rank,
                "votes": votes,
                "comment_count": comments,
                "topics": topics,
                "website": row.get("website"),
                "discovery_type": "product_launch",
            },
        )

    async def _fetch_feed(self, since: datetime) -> List[ContentItem]:
        try:
            response = await self.client.get(
                self.cfg.feed_url,
                headers={"Accept": "application/atom+xml", "User-Agent": "Horizon/1.0"},
                follow_redirects=True,
                timeout=25.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Error fetching Product Hunt feed: %s", exc)
            return []

        parsed = feedparser.parse(response.content)
        items: list[ContentItem] = []
        for position, entry in enumerate(parsed.entries, start=1):
            published_at = _parse_datetime(entry.get("published"))
            if published_at is None or published_at < since:
                continue
            title = str(entry.get("title") or "").strip()
            url = entry.get("link")
            if not title or not url:
                continue
            raw_content = (entry.get("content") or [{}])[0].get("value", "")
            soup = BeautifulSoup(raw_content, "html.parser")
            paragraphs = [node.get_text(" ", strip=True) for node in soup.find_all("p")]
            tagline = paragraphs[0] if paragraphs else soup.get_text(" ", strip=True)
            if self.cfg.ai_only and not matches_keywords(
                [title, tagline], self.cfg.keywords
            ):
                continue
            id_match = re.search(r"Post/(\d+)", str(entry.get("id") or ""))
            native_id = id_match.group(1) if id_match else str(entry.get("id") or title)
            items.append(
                ContentItem(
                    id=self._generate_id("producthunt", "post", native_id),
                    source_type=SourceType.PRODUCTHUNT,
                    title=title,
                    url=url,
                    content=(
                        f"{tagline}\n\nProduct Hunt public feed position: #{position}. "
                        "Vote and comment totals are unavailable without an API token."
                    ),
                    author=(entry.get("author_detail") or {}).get("name") or entry.get("author"),
                    published_at=published_at,
                    metadata={
                        "category": self.cfg.category,
                        "radar_source": "producthunt",
                        "radar_signals": [
                            {
                                "source": "producthunt",
                                "rank": None,
                                "feed_position": position,
                                "mode": "rss_fallback",
                            }
                        ],
                        "feed_position": position,
                        "api_metrics_available": False,
                        "discovery_type": "product_launch",
                    },
                )
            )
            if len(items) >= self.cfg.max_items:
                break
        return items


class YCProductsScraper(BaseScraper):
    """Fetch YC Launches and use the YC AI directory as a validation signal."""

    LAUNCHES_URL = "https://www.ycombinator.com/launches"
    AI_DIRECTORY_URL = "https://www.ycombinator.com/companies/industry/ai"

    def __init__(self, config: YCProductsConfig, http_client: httpx.AsyncClient):
        super().__init__(config, http_client)
        self.cfg = config

    async def fetch(self, since: datetime) -> List[ContentItem]:
        if not self.cfg.enabled:
            return []
        ai_company_slugs = (
            await self._fetch_ai_directory_slugs()
            if self.cfg.validate_ai_directory
            else set()
        )
        try:
            response = await self.client.get(
                self.LAUNCHES_URL,
                headers={"Accept": "application/json", "User-Agent": "Horizon/1.0"},
                follow_redirects=True,
                timeout=25.0,
            )
            response.raise_for_status()
            rows = response.json().get("hits") or []
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Error fetching YC Launches: %s", exc)
            return []

        items: list[ContentItem] = []
        for rank, row in enumerate(rows, start=1):
            item = self._row_to_item(row, rank, since, ai_company_slugs)
            if item is not None:
                items.append(item)
            if len(items) >= self.cfg.max_items:
                break
        return items

    async def _fetch_ai_directory_slugs(self) -> set[str]:
        try:
            response = await self.client.get(
                self.AI_DIRECTORY_URL,
                headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0 Horizon/1.0"},
                follow_redirects=True,
                timeout=25.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Error fetching YC AI directory: %s", exc)
            return set()
        return set(re.findall(r'href=["\']/companies/([a-z0-9-]+)["\']', response.text, re.I))

    def _row_to_item(
        self,
        row: dict[str, Any],
        rank: int,
        since: datetime,
        ai_company_slugs: set[str],
    ) -> Optional[ContentItem]:
        published_at = _parse_datetime(row.get("created_at"))
        if published_at is None or published_at < since:
            return None
        company = row.get("company") or {}
        tags = company.get("tags") or []
        company_slug = str(company.get("slug") or "")
        directory_match = company_slug in ai_company_slugs
        ai_text_match = matches_keywords(
            [row.get("title"), row.get("tagline"), " ".join(tags)],
            DEFAULT_AI_RADAR_KEYWORDS,
        )
        if self.cfg.ai_only and not (directory_match or ai_text_match):
            return None

        votes = coerce_int(row.get("total_vote_count"))
        title = str(row.get("title") or "").strip()
        url = row.get("search_path")
        if not title or not url:
            return None
        return ContentItem(
            id=self._generate_id("yc", "launch", str(row.get("id") or title)),
            source_type=SourceType.YC,
            title=title,
            url=url,
            content=(
                f"{row.get('tagline') or ''}\n\nYC votes: {votes}\n"
                f"Company: {company.get('name') or 'unknown'}\n"
                f"Batch: {company.get('batch') or 'unknown'}\n"
                f"Industry: {company.get('industry') or 'unknown'}\n"
                f"Tags: {', '.join(tags)}\n"
                f"YC AI directory match: {'yes' if directory_match else 'not in visible directory page'}"
            ),
            author=company.get("name"),
            published_at=published_at,
            metadata={
                "category": self.cfg.category,
                "radar_source": "yc_launches",
                "radar_signals": [
                    {
                        "source": "yc_launches",
                        "rank": rank,
                        "votes": votes,
                        "yc_ai_directory_match": directory_match,
                    }
                ],
                "yc_launch_rank": rank,
                "votes": votes,
                "company": company.get("name"),
                "company_slug": company_slug,
                "company_url": company.get("url"),
                "company_tags": tags,
                "yc_batch": company.get("batch"),
                "yc_ai_directory_match": directory_match,
                "discovery_type": "yc_launch",
            },
        )


class HuggingFaceSpacesScraper(BaseScraper):
    """Fetch trending public demos from the Hugging Face Hub endpoint."""

    API_URL = "https://huggingface.co/api/spaces"

    def __init__(
        self,
        config: HuggingFaceSpacesConfig,
        http_client: httpx.AsyncClient,
    ):
        super().__init__(config, http_client)
        self.cfg = config

    async def fetch(self, since: datetime) -> List[ContentItem]:
        if not self.cfg.enabled:
            return []
        try:
            response = await self.client.get(
                self.API_URL,
                # The public endpoint's default ordering is the same trending
                # order used by the Spaces directory. ``sort=trending`` is not
                # an accepted parameter, so it is intentionally omitted.
                params={"limit": self.cfg.max_items * 2, "full": "true"},
                headers={"Accept": "application/json", "User-Agent": "Horizon/1.0"},
                follow_redirects=True,
                timeout=25.0,
            )
            response.raise_for_status()
            rows = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Error fetching Hugging Face Spaces: %s", exc)
            return []

        oldest = max(
            since,
            datetime.now(timezone.utc) - timedelta(days=self.cfg.max_age_days),
        )
        items: list[ContentItem] = []
        for rank, row in enumerate(rows, start=1):
            item = self._row_to_item(row, rank, oldest)
            if item is not None:
                items.append(item)
            if len(items) >= self.cfg.max_items:
                break
        return items

    def _row_to_item(
        self,
        row: dict[str, Any],
        rank: int,
        oldest: datetime,
    ) -> Optional[ContentItem]:
        space_id = str(row.get("id") or row.get("modelId") or "")
        if space_id.count("/") != 1 or row.get("private"):
            return None
        likes = coerce_int(row.get("likes"))
        trending_score = float(row.get("trendingScore") or 0)
        if likes < self.cfg.min_likes:
            return None
        activity_times = [
            timestamp
            for timestamp in (
                _parse_datetime(row.get("createdAt")),
                _parse_datetime(row.get("lastModified")),
            )
            if timestamp is not None
        ]
        published_at = max(activity_times) if activity_times else datetime.now(timezone.utc)
        if published_at < oldest:
            return None
        card = row.get("cardData") or {}
        title = str(card.get("title") or space_id)
        description = str(card.get("short_description") or card.get("description") or "")
        tags = row.get("tags") or []
        return ContentItem(
            id=self._generate_id("huggingface", "space", space_id.lower()),
            source_type=SourceType.HUGGINGFACE,
            title=title,
            url=f"https://huggingface.co/spaces/{space_id}",
            content=(
                f"{description}\n\nHugging Face Spaces trending rank: #{rank}\n"
                f"Likes: {likes}\nSDK: {row.get('sdk') or card.get('sdk') or 'unknown'}\n"
                f"Tags: {', '.join(tags)}"
            ),
            author=space_id.split("/", 1)[0],
            published_at=published_at,
            metadata={
                "category": self.cfg.category,
                "radar_source": "huggingface_spaces",
                "radar_signals": [
                    {
                        "source": "huggingface_spaces",
                        "rank": rank,
                        "likes": likes,
                        "trending_score": trending_score,
                    }
                ],
                "huggingface_rank": rank,
                "likes": likes,
                "trending_score": trending_score,
                "sdk": row.get("sdk") or card.get("sdk"),
                "tags": tags,
                "discovery_type": "ai_demo",
            },
        )
