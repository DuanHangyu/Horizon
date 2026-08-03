"""GitHub scraper implementation."""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import httpx

from .base import BaseScraper
from ..models import ContentItem, SourceType, GitHubSourceConfig

logger = logging.getLogger(__name__)


class GitHubScraper(BaseScraper):
    """Scraper for GitHub events and releases."""

    def __init__(self, sources: List[GitHubSourceConfig], http_client: httpx.AsyncClient):
        """Initialize GitHub scraper.

        Args:
            sources: List of GitHub source configurations
            http_client: Shared async HTTP client
        """
        super().__init__({"sources": sources}, http_client)
        self.token = os.getenv("GITHUB_TOKEN")
        self.base_url = "https://api.github.com"

    def _get_headers(self) -> dict:
        """Get request headers with optional authentication.

        Returns:
            dict: HTTP headers
        """
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Horizon-Aggregator"
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        return headers

    async def fetch(self, since: datetime) -> List[ContentItem]:
        """Fetch GitHub content items.

        Args:
            since: Only fetch items published after this time

        Returns:
            List[ContentItem]: Fetched content items
        """
        items = []
        sources = self.config["sources"]

        for source in sources:
            if not source.enabled:
                continue

            if source.type == "user_events" and source.username:
                user_items = await self._fetch_user_events(source, since)
                items.extend(user_items)
            elif source.type == "repo_releases" and source.owner and source.repo:
                release_items = await self._fetch_repo_releases(source, since)
                items.extend(release_items)
            elif source.type == "repo_search" and source.query:
                search_items = await self._fetch_repo_search(source)
                items.extend(search_items)

        return items

    async def _fetch_user_events(
        self,
        source: GitHubSourceConfig,
        since: datetime
    ) -> List[ContentItem]:
        """Fetch public events for a user.

        Args:
            username: GitHub username
            since: Only fetch events after this time

        Returns:
            List[ContentItem]: Event content items
        """
        username = source.username
        if not username:
            return []

        url = f"{self.base_url}/users/{username}/events/public"
        items = []

        try:
            response = await self.client.get(url, headers=self._get_headers(), follow_redirects=True)
            response.raise_for_status()
            events = response.json()

            for event in events:
                created_at = datetime.fromisoformat(
                    event["created_at"].replace("Z", "+00:00")
                )

                if created_at < since:
                    continue

                # Filter interesting event types
                event_type = event["type"]
                if event_type not in [
                    "PushEvent", "CreateEvent", "ReleaseEvent",
                    "PublicEvent", "WatchEvent"
                ]:
                    continue

                item = self._parse_event(event, username, source.category)
                if item:
                    items.append(item)

        except httpx.HTTPError as e:
            logger.warning("Error fetching GitHub events for %s: %s", username, e)

        return items

    def _parse_event(
        self,
        event: dict,
        username: str,
        category: Optional[str] = None,
    ) -> Optional[ContentItem]:
        """Parse GitHub event into ContentItem.

        Args:
            event: GitHub event data
            username: GitHub username

        Returns:
            Optional[ContentItem]: Parsed content item or None
        """
        event_type = event["type"]
        event_id = event["id"]
        created_at = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))

        repo_name = event["repo"]["name"]
        repo_url = f"https://github.com/{repo_name}"

        # Generate title and content based on event type
        if event_type == "PushEvent":
            commits = event["payload"].get("commits", [])
            title = f"{username} pushed {len(commits)} commit(s) to {repo_name}"
            content = "\n".join([c.get("message", "") for c in commits[:3]])
        elif event_type == "CreateEvent":
            ref_type = event["payload"].get("ref_type", "repository")
            title = f"{username} created {ref_type} in {repo_name}"
            content = event["payload"].get("description", "")
        elif event_type == "ReleaseEvent":
            release = event["payload"].get("release", {})
            title = f"{username} released {release.get('tag_name', '')} in {repo_name}"
            content = release.get("body", "")
            repo_url = release.get("html_url", repo_url)
        elif event_type == "PublicEvent":
            title = f"{username} made {repo_name} public"
            content = ""
        elif event_type == "WatchEvent":
            title = f"{username} starred {repo_name}"
            content = ""
        else:
            return None

        return ContentItem(
            id=self._generate_id("github", "event", event_id),
            source_type=SourceType.GITHUB,
            title=title,
            url=repo_url,
            content=content,
            author=username,
            published_at=created_at,
            metadata={
                "event_type": event_type,
                "repo": repo_name,
                "category": category,
            }
        )

    async def _fetch_repo_releases(
        self,
        source: GitHubSourceConfig,
        since: datetime
    ) -> List[ContentItem]:
        """Fetch releases for a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            since: Only fetch releases after this time

        Returns:
            List[ContentItem]: Release content items
        """
        owner = source.owner
        repo = source.repo
        if not owner or not repo:
            return []

        url = f"{self.base_url}/repos/{owner}/{repo}/releases"
        items = []

        try:
            response = await self.client.get(url, headers=self._get_headers(), follow_redirects=True)
            response.raise_for_status()
            releases = response.json()

            for release in releases:
                published_at = datetime.fromisoformat(
                    release["published_at"].replace("Z", "+00:00")
                )

                if published_at < since:
                    continue

                item = ContentItem(
                    id=self._generate_id("github", "release", str(release["id"])),
                    source_type=SourceType.GITHUB,
                    title=f"{owner}/{repo} released {release['tag_name']}",
                    url=release["html_url"],
                    content=release.get("body", ""),
                    author=release["author"]["login"],
                    published_at=published_at,
                    metadata={
                        "repo": f"{owner}/{repo}",
                        "tag": release["tag_name"],
                        "prerelease": release.get("prerelease", False),
                        "category": source.category,
                    }
                )
                items.append(item)

        except httpx.HTTPError as e:
            logger.warning("Error fetching releases for %s/%s: %s", owner, repo, e)

        return items

    async def _fetch_repo_search(
        self,
        source: GitHubSourceConfig,
    ) -> List[ContentItem]:
        """Discover recently-created repositories matching a GitHub query."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=source.lookback_days)
        query_parts = [source.query or "", f"created:>={cutoff:%Y-%m-%d}"]
        if source.min_stars:
            query_parts.append(f"stars:>={source.min_stars}")

        params = {
            "q": " ".join(part for part in query_parts if part).strip(),
            "sort": source.sort,
            "order": source.order,
            "per_page": source.max_items,
        }
        try:
            response = await self.client.get(
                f"{self.base_url}/search/repositories",
                params=params,
                headers=self._get_headers(),
                follow_redirects=True,
                timeout=20.0,
            )
            response.raise_for_status()
            rows = response.json().get("items") or []
        except httpx.HTTPError as exc:
            logger.warning("Error searching GitHub repositories for %s: %s", source.query, exc)
            return []

        items: List[ContentItem] = []
        for row in rows:
            repo_id = row.get("id")
            repo_name = row.get("full_name")
            html_url = row.get("html_url")
            if repo_id is None or not repo_name or not html_url:
                continue

            created_at = self._parse_github_datetime(row.get("created_at"))
            pushed_at = self._parse_github_datetime(row.get("pushed_at"))
            topics = row.get("topics") or []
            description = (row.get("description") or "").strip()
            stars = int(row.get("stargazers_count") or 0)
            forks = int(row.get("forks_count") or 0)

            content_lines = [
                f"GitHub repository: {repo_name}",
                f"Stars: {stars}",
                f"Forks: {forks}",
                f"Primary language: {row.get('language') or 'unknown'}",
                f"Created: {created_at.isoformat()}",
                f"Last pushed: {pushed_at.isoformat()}",
            ]
            if topics:
                content_lines.append(f"Topics: {', '.join(topics)}")
            if description:
                content_lines.extend(["", description])

            items.append(
                ContentItem(
                    id=self._generate_id("github", "repo", str(repo_id)),
                    source_type=SourceType.GITHUB,
                    title=f"{repo_name} ({stars}⭐)",
                    url=html_url,
                    content="\n".join(content_lines),
                    author=(row.get("owner") or {}).get("login"),
                    published_at=created_at,
                    metadata={
                        "repo": repo_name,
                        "category": source.category,
                        "discovery_type": "recent_repo_search",
                        "stargazers_count": stars,
                        "forks_count": forks,
                        "open_issues_count": int(row.get("open_issues_count") or 0),
                        "primary_language": row.get("language"),
                        "topics": topics,
                        "license": (row.get("license") or {}).get("spdx_id"),
                        "created_at": created_at.isoformat(),
                        "pushed_at": pushed_at.isoformat(),
                        "homepage": row.get("homepage"),
                    },
                )
            )

        return items

    @staticmethod
    def _parse_github_datetime(value: Optional[str]) -> datetime:
        """Parse a GitHub timestamp, falling back to the current UTC time."""
        if not value:
            return datetime.now(timezone.utc)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
