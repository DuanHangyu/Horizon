"""Content analysis using AI."""

import asyncio
import json
import math
import re
from typing import List, Optional
from tenacity import retry, stop_after_attempt, wait_exponential
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, MofNCompleteColumn

from .client import AIClient
from .prompts import (
    CONTENT_ANALYSIS_SYSTEM,
    CONTENT_ANALYSIS_USER,
    OSS_ANALYSIS_SYSTEM,
    PRODUCT_ANALYSIS_SYSTEM,
)
from .utils import parse_json_response
from ..models import ContentItem

DEFAULT_THROTTLE_SEC = 0.0


class ContentAnalyzer:
    """Analyzes content items using AI to determine importance."""

    def __init__(self, ai_client: AIClient):
        self.client = ai_client

    @staticmethod
    def _parse_json_response(response: str) -> Optional[dict]:
        """Try multiple strategies to extract a JSON object from an AI response.

        Returns the parsed dict, or None if all strategies fail.
        """
        return parse_json_response(response)

    def _get_throttle_sec(self) -> float:
        """Return the configured inter-item throttle, clamped to zero or above."""
        config = getattr(self.client, "config", None)
        throttle_sec = getattr(config, "throttle_sec", DEFAULT_THROTTLE_SEC)
        return max(throttle_sec, 0.0)

    def _get_concurrency(self) -> int:
        """Return the configured analysis concurrency, clamped to 1 or above."""
        config = getattr(self.client, "config", None)
        concurrency = getattr(config, "analysis_concurrency", 1)
        return max(concurrency, 1)

    @staticmethod
    def _system_prompt_for(item: ContentItem) -> str:
        """Choose the rubric that matches the item's configured digest lane."""
        category = item.metadata.get("category")
        if category in {"ai-products", "startup-products"}:
            return PRODUCT_ANALYSIS_SYSTEM
        if category == "github-trending":
            return OSS_ANALYSIS_SYSTEM
        return CONTENT_ANALYSIS_SYSTEM

    @staticmethod
    def _radar_evidence(item: ContentItem) -> tuple[Optional[float], str]:
        """Calculate a deterministic 0-10 strength score for radar evidence."""
        signals = [
            signal
            for signal in (item.metadata.get("radar_signals") or [])
            if isinstance(signal, dict) and signal.get("source")
        ]
        if not signals:
            return None, ""

        scores: list[float] = []
        summaries: list[str] = []
        source_names: set[str] = set()
        for signal in signals:
            source = str(signal["source"])
            source_names.add(source)
            rank = signal.get("rank")
            rank_value = int(rank) if isinstance(rank, (int, float)) and rank else None
            stars = int(signal.get("stars_gained") or 0)
            votes = int(signal.get("votes") or signal.get("points") or 0)
            comments = int(signal.get("comments") or 0)
            likes = int(signal.get("likes") or 0)

            if source == "github_trending":
                score = 8.0 if rank_value is None else max(5.5, 9.8 - 0.18 * (rank_value - 1))
                score += min(0.7, math.log10(stars + 1) * 0.2)
                summaries.append(
                    f"GitHub Trending #{rank_value or '?'}"
                    + (f" (+{stars}★)" if stars else "")
                )
            elif source == "trendshift":
                score = 7.5 if rank_value is None else max(5.5, 9.3 - 0.16 * (rank_value - 1))
                score += min(0.7, math.log10(stars + 1) * 0.2)
                summaries.append(f"Trendshift #{rank_value or '?'}")
            elif source == "ossinsight":
                score = 5.5 + min(4.0, math.log10(stars + 1) * 1.7)
                summaries.append(f"OSSInsight +{stars}★")
            elif source == "producthunt":
                score = 5.5 + min(3.5, math.log10(votes + 1) * 1.4)
                if rank_value:
                    score += max(0.0, 0.8 - 0.05 * (rank_value - 1))
                summaries.append(
                    f"Product Hunt #{rank_value}" if rank_value else "Product Hunt RSS"
                )
            elif source == "yc_launches":
                score = 7.0 + min(2.0, math.log10(votes + 1))
                if signal.get("yc_ai_directory_match"):
                    score += 0.5
                summaries.append(f"YC Launches ({votes} votes)")
            elif source == "huggingface_spaces":
                score = 6.0 + min(2.5, math.log10(likes + 1) * 1.2)
                if rank_value:
                    score += max(0.0, 0.8 - 0.04 * (rank_value - 1))
                summaries.append(f"HF Spaces #{rank_value or '?'} ({likes} likes)")
            elif source == "show_hn":
                score = 5.5 + min(2.5, math.log10(votes + 1) * 1.2)
                score += min(0.8, math.log10(comments + 1) * 0.35)
                summaries.append(f"Show HN ({votes} points/{comments} comments)")
            else:
                score = 5.0
                summaries.append(source)
            scores.append(min(10.0, score))

        consensus_bonus = min(1.0, max(0, len(source_names) - 1) * 0.5)
        evidence_score = min(10.0, max(scores) + consensus_bonus)
        return round(evidence_score, 1), " · ".join(summaries)

    @classmethod
    def _calibrate_radar_score(cls, item: ContentItem, semantic_score: float) -> float:
        """Blend AI relevance/utility with auditable platform momentum."""
        evidence_score, evidence_summary = cls._radar_evidence(item)
        if evidence_score is None:
            return semantic_score

        item.metadata["semantic_score"] = round(semantic_score, 1)
        item.metadata["radar_evidence_score"] = evidence_score
        item.metadata["radar_signal_summary"] = evidence_summary

        # A ranking cannot rescue a non-AI or non-product item. Only items that
        # clear the semantic rubric may benefit from platform momentum.
        if semantic_score < 7.0:
            return min(6.9, semantic_score)
        return round(min(10.0, semantic_score * 0.75 + evidence_score * 0.25), 1)

    async def analyze_batch(self, items: List[ContentItem]) -> List[ContentItem]:
        throttle_sec = self._get_throttle_sec()
        concurrency = self._get_concurrency()
        semaphore = asyncio.Semaphore(concurrency)

        async def _process(item: ContentItem, index: int, progress_task) -> ContentItem:
            async with semaphore:
                try:
                    await self._analyze_item(item)
                except Exception as e:
                    print(f"Error analyzing item {item.id}: {e}")
                    item.ai_score = 0.0
                    item.ai_reason = "Analysis failed"
                    item.ai_summary = item.title
                if throttle_sec > 0 and index < len(items) - 1:
                    await asyncio.sleep(throttle_sec)
            progress.advance(progress_task)
            return item

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task("Analyzing", total=len(items))
            coros = [
                _process(item, i, task) for i, item in enumerate(items)
            ]
            analyzed_items = await asyncio.gather(*coros)

        return analyzed_items

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=10)
    )
    async def _analyze_item(self, item: ContentItem) -> None:
        """Analyze a single content item.

        Args:
            item: Content item to analyze (modified in-place)
        """
        # Prepare content section
        content_section = ""
        if item.content:
            # Split off comments if present
            content_text = item.content
            if "--- Top Comments ---" in content_text:
                main, comments_part = content_text.split("--- Top Comments ---", 1)
                content_section = f"Content: {main.strip()[:800]}"
            else:
                content_section = f"Content: {content_text[:1000]}"

        # Prepare discussion section (comments, engagement)
        discussion_parts = []
        if item.content and "--- Top Comments ---" in item.content:
            comments_part = item.content.split("--- Top Comments ---", 1)[1]
            discussion_parts.append(f"Community Comments:\n{comments_part[:1500]}")

        meta = item.metadata
        engagement_items = []
        if meta.get("score"):
            engagement_items.append(f"score: {meta['score']}")
        if meta.get("descendants"):
            engagement_items.append(f"{meta['descendants']} comments")
        if meta.get("favorite_count"):
            engagement_items.append(f"{meta['favorite_count']} likes")
        if meta.get("retweet_count"):
            engagement_items.append(f"{meta['retweet_count']} retweets")
        if meta.get("reply_count"):
            engagement_items.append(f"{meta['reply_count']} replies")
        if meta.get("views"):
            engagement_items.append(f"{meta['views']} views")
        if meta.get("bookmarks"):
            engagement_items.append(f"{meta['bookmarks']} bookmarks")
        if meta.get("votes") is not None:
            engagement_items.append(f"{meta['votes']} votes")
        if meta.get("likes") is not None:
            engagement_items.append(f"{meta['likes']} likes")
        if meta.get("stars_gained") is not None:
            engagement_items.append(f"{meta['stars_gained']} stars gained")
        if meta.get("stargazers_count") is not None:
            engagement_items.append(f"{meta['stargazers_count']} total stars")
        if meta.get("forks_count") is not None:
            engagement_items.append(f"{meta['forks_count']} forks")
        if meta.get("pushes") is not None:
            engagement_items.append(f"{meta['pushes']} pushes")
        if meta.get("pull_requests") is not None:
            engagement_items.append(f"{meta['pull_requests']} pull requests")
        if meta.get("upvote_ratio"):
            engagement_items.append(f"upvote ratio: {meta['upvote_ratio']:.0%}")
        if engagement_items:
            discussion_parts.append(f"Engagement: {', '.join(engagement_items)}")
        evidence_score, evidence_summary = self._radar_evidence(item)
        if evidence_score is not None:
            discussion_parts.append(
                f"Radar evidence: {evidence_summary} (deterministic strength {evidence_score}/10)"
            )
        if meta.get("discussion_url"):
            discussion_parts.append(f"Discussion: {meta['discussion_url']}")
        if meta.get("community_note"):
            discussion_parts.append(f"Community Note: {meta['community_note']}")

        discussion_section = "\n".join(discussion_parts) if discussion_parts else ""

        # Generate user prompt
        user_prompt = CONTENT_ANALYSIS_USER.format(
            title=item.title,
            source=f"{item.source_type.value}",
            author=item.author or "Unknown",
            url=str(item.url),
            content_section=content_section,
            discussion_section=discussion_section
        )

        # Get AI completion
        response = await self.client.complete(
            system=self._system_prompt_for(item),
            user=user_prompt,
        )

        # Parse JSON response with robust fallback
        result = self._parse_json_response(response)
        if result is None:
            print(f"Warning: could not parse analysis response for {item.id}, using defaults")
            item.ai_score = 0.0
            item.ai_reason = "Analysis response parse failed"
            item.ai_summary = item.title
            item.ai_tags = []
            return

        # Update item with analysis results
        semantic_score = max(0.0, min(10.0, float(result.get("score", 0))))
        item.ai_score = self._calibrate_radar_score(item, semantic_score)
        item.ai_reason = result.get("reason", "")
        item.ai_summary = result.get("summary", item.title)
        item.ai_tags = result.get("tags", [])
