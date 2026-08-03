"""Daily summary generation — pure programmatic rendering."""

import re
from typing import Any, List, Dict, Optional

from ..models import ContentItem


_CJK = r"[\u4e00-\u9fff\u3400-\u4dbf]"
_ASCII = r"[A-Za-z0-9]"


def _pangu(text: str) -> str:
    """Insert a space between CJK and ASCII letters/digits (Pangu spacing)."""
    text = re.sub(rf"({_CJK})({_ASCII})", r"\1 \2", text)
    text = re.sub(rf"({_ASCII})({_CJK})", r"\1 \2", text)
    return text


LABELS = {
    "en": {
        "header": "Horizon Daily",
        "source": "Source",
        "background": "Background",
        "discussion": "Discussion",
        "references": "References",
        "tags": "Tags",
        "contents": "Contents",
        "radar_signal": "Radar signal",
        "uncategorized_section": "Other Updates",
        "selected_items": "From {total} items, {selected} important content pieces were selected",
        "empty_analyzed": "Analyzed {total} items, but none met the importance threshold.",
        "empty_body": (
            "No significant developments today. This might indicate:\n"
            "- A quiet day in your tracked sources\n"
            "- The AI score threshold is too high\n"
            "- Your information sources need expansion\n\n"
            "Consider:\n"
            "1. Lowering the `ai_score_threshold` in config.json\n"
            "2. Adding more diverse information sources\n"
            "3. Checking if the AI model is working correctly\n"
        ),
    },
    "zh": {
        "header": "Horizon 每日速递",
        "source": "来源",
        "background": "背景",
        "discussion": "社区讨论",
        "references": "参考链接",
        "tags": "标签",
        "contents": "目录",
        "radar_signal": "热度信号",
        "uncategorized_section": "其他资讯",
        "selected_items": "从 {total} 条内容中筛选出 {selected} 条重要资讯。",
        "empty_analyzed": "已分析 {total} 条内容，但没有达到重要性阈值的条目。",
        "empty_body": (
            "今日暂无重要动态，可能原因：\n"
            "- 今天关注的信息源较平静\n"
            "- AI 评分阈值设置过高\n"
            "- 信息源种类有待扩充\n\n"
            "建议：\n"
            "1. 在 config.json 中降低 `ai_score_threshold`\n"
            "2. 添加更多多样化的信息源\n"
            "3. 检查 AI 模型是否正常工作\n"
        ),
    },
}


class DailySummarizer:
    """Generates daily Markdown summaries from pre-analyzed content items."""

    def __init__(self):
        pass

    async def generate_summary(
        self,
        items: List[ContentItem],
        date: str,
        total_fetched: int,
        language: str = "en",
    ) -> str:
        """Generate daily summary in Markdown format.

        Items are rendered in score-descending order (already sorted by orchestrator).

        Args:
            items: High-scoring content items (already enriched)
            date: Date string (YYYY-MM-DD)
            total_fetched: Total number of items fetched before filtering
            language: Output language, either "en" or "zh"

        Returns:
            str: Markdown formatted summary
        """
        labels = LABELS.get(language, LABELS["en"])

        if not items:
            return self._generate_empty_summary(date, total_fetched, labels)

        header = (
            f"# {labels['header']} - {date}\n\n"
            f"> {labels['selected_items'].format(total=total_fetched, selected=len(items))}\n\n"
            "---\n\n"
        )

        sections = self._group_by_section(items, labels)
        is_sectioned = any(section_key is not None for section_key, _, _ in sections)

        # TOC
        toc_entries = []
        item_index = 0
        if is_sectioned:
            toc_entries.extend([f"## {labels['contents']}", ""])
        for section_key, section_name, section_items in sections:
            if section_key is not None:
                toc_entries.extend([f"### {section_name}（{len(section_items)}）", ""])
            for item in section_items:
                item_index += 1
                _t = item.metadata.get(f"title_{language}") or item.title
                t = str(_t).replace("[", "(").replace("]", ")")
                if language == "zh":
                    t = _pangu(t)
                score = item.ai_score or "?"
                toc_entries.append(f"{item_index}. [{t}](#item-{item_index}) \u2b50\ufe0f {score}/10")
            if section_key is not None:
                toc_entries.append("")
        toc = "\n".join(toc_entries).rstrip() + "\n\n---\n\n"

        parts = []
        item_index = 0
        for section_key, section_name, section_items in sections:
            if section_key is not None:
                parts.append(f"## {section_name}（{len(section_items)}）\n\n")
            for item in section_items:
                item_index += 1
                parts.append(
                    self._format_item(
                        item,
                        labels,
                        language,
                        item_index,
                        heading_level=3 if is_sectioned else 2,
                    )
                )

        return header + toc + "".join(parts)

    def generate_webhook_overview(
        self,
        items: List[ContentItem],
        date: str,
        total_fetched: int,
        language: str = "en",
    ) -> str:
        """Generate a compact overview for multi-message webhook delivery."""
        labels = LABELS.get(language, LABELS["en"])
        if not items:
            return self._generate_empty_summary(date, total_fetched, labels)

        if language == "zh":
            header = (
                f"# {labels['header']} - {date}\n\n"
                f"> 从 {total_fetched} 条内容中筛选出 {len(items)} 条重要资讯。\n\n"
                "下面会按新闻逐条发送详情，你可以只看感兴趣的标题。\n\n"
            )
        else:
            header = (
                f"# {labels['header']} - {date}\n\n"
                f"> Selected {len(items)} important items from {total_fetched} fetched items.\n\n"
                "Details will be sent item by item so you can read only the topics you care about.\n\n"
            )

        entries = []
        item_index = 0
        for section_key, section_name, section_items in self._group_by_section(items, labels):
            if section_key is not None:
                entries.extend([f"## {section_name}（{len(section_items)}）", ""])
            for item in section_items:
                item_index += 1
                title = str(item.metadata.get(f"title_{language}") or item.title).replace("[", "(").replace("]", ")")
                if language == "zh":
                    title = _pangu(title)
                score = item.ai_score or "?"
                entries.append(f"{item_index}. [{title}]({item.url}) \u2b50\ufe0f {score}/10")
            if section_key is not None:
                entries.append("")

        return header + "\n".join(entries).rstrip()

    def generate_webhook_section_overviews(
        self,
        items: List[ContentItem],
        date: str,
        total_fetched: int,
        language: str = "en",
        max_bytes: int = 14_000,
    ) -> List[Dict[str, Any]]:
        """Generate compact, byte-bounded webhook overviews per digest section.

        Feishu custom-bot payloads are limited to 20 KB. This renderer keeps
        each Markdown body comfortably below that ceiling and splits an
        unusually large section into multiple messages without dropping items.
        """
        labels = LABELS.get(language, LABELS["en"])
        sections = self._group_by_section(items, labels)
        overviews: List[Dict[str, Any]] = []

        # Reserve space for the card JSON, title, header, and chunk indicator.
        entry_budget = max(1_000, max_bytes - 1_000)

        for section_index, (section_key, section_name, section_items) in enumerate(
            sections, start=1
        ):
            display_name = section_name or labels["header"]
            entry_lines: List[str] = []
            for item_index, item in enumerate(section_items, start=1):
                raw_title = item.metadata.get(f"title_{language}") or item.title
                title = str(raw_title).replace("[", "(").replace("]", ")")
                if language == "zh":
                    title = _pangu(title)
                score = item.ai_score or "?"
                source = item.metadata.get("radar_source") or item.source_type.value
                entry_lines.append(
                    f"{item_index}. [{title}]({item.url}) · ⭐ {score}/10 · {source}"
                )

            chunks: List[List[str]] = []
            current: List[str] = []
            current_bytes = 0
            for line in entry_lines:
                line_bytes = len((line + "\n").encode("utf-8"))
                if current and current_bytes + line_bytes > entry_budget:
                    chunks.append(current)
                    current = []
                    current_bytes = 0
                current.append(line)
                current_bytes += line_bytes
            if current or not chunks:
                chunks.append(current)

            for chunk_index, chunk_lines in enumerate(chunks, start=1):
                page_suffix = (
                    f"（{chunk_index}/{len(chunks)}）" if len(chunks) > 1 else ""
                )
                if language == "zh":
                    header = (
                        f"## {display_name}{page_suffix}\n\n"
                        f"> Horizon 从 {total_fetched} 条候选信息中筛选出 "
                        f"{len(items)} 条；本部分共 {len(section_items)} 条。\n\n"
                    )
                else:
                    header = (
                        f"## {display_name}{page_suffix}\n\n"
                        f"> Horizon selected {len(items)} items from {total_fetched}; "
                        f"this section contains {len(section_items)} items.\n\n"
                    )

                overviews.append(
                    {
                        "section_key": section_key or "daily",
                        "section_name": display_name,
                        "section_index": section_index,
                        "section_count": len(sections),
                        "section_item_count": len(section_items),
                        "chunk_index": chunk_index,
                        "chunk_count": len(chunks),
                        "summary": header + "\n".join(chunk_lines),
                    }
                )

        return overviews

    def generate_webhook_item(
        self,
        item: ContentItem,
        language: str,
        index: int,
        total: int,
    ) -> str:
        """Generate one item message for multi-message webhook delivery."""
        labels = LABELS.get(language, LABELS["en"])
        prefix = f"第 {index}/{total} 条\n\n" if language == "zh" else f"Item {index}/{total}\n\n"
        return prefix + self._format_item(item, labels, language, index).rstrip("-\n ")

    def _format_item(
        self,
        item: ContentItem,
        labels: dict,
        language: str,
        index: int,
        *,
        heading_level: int = 2,
    ) -> str:
        """Format a single ContentItem into Markdown."""
        _title = item.metadata.get(f"title_{language}") or item.title
        title = str(_title).replace("[", "(").replace("]", ")")
        url = str(item.url)
        score = item.ai_score or "?"
        meta = item.metadata

        summary = (
            meta.get(f"detailed_summary_{language}")
            or meta.get("detailed_summary")
            or item.ai_summary
            or ""
        )
        background = meta.get(f"background_{language}") or meta.get("background") or ""
        discussion = (
            meta.get(f"community_discussion_{language}")
            or meta.get("community_discussion")
            or ""
        )

        if language == "zh":
            title = _pangu(title)
            summary = _pangu(summary)
            background = _pangu(background)
            discussion = _pangu(discussion)

        # Source line with parts joined by " · ", link appended at end
        merged_sources = meta.get("merged_sources") or []
        source_names = [item.source_type.value]
        source_names.extend(
            source for source in merged_sources if source not in source_names
        )
        source_type = "+".join(source_names)
        source_parts = [source_type]
        if meta.get("subreddit"):
            source_parts.append(f"r/{meta['subreddit']}")
        if meta.get("feed_name"):
            source_parts.append(meta["feed_name"])
        else:
            source_parts.append(item.author or "unknown")
        if item.published_at:
            if language == "zh":
                source_parts.append(
                    f"{item.published_at.month}月{item.published_at.day}日 "
                    f"{item.published_at:%H:%M}"
                )
            else:
                day = item.published_at.strftime("%d").lstrip("0")
                source_parts.append(item.published_at.strftime(f"%b {day}, %H:%M"))
        source_line = " \u00b7 ".join(source_parts)  # ·

        discussion_url = meta.get("discussion_url")
        if discussion_url:
            discussion_url = str(discussion_url)
            if discussion_url != url:
                source_line += f' · [{labels["discussion"]}]({discussion_url})'
        if meta.get("radar_signal_summary"):
            source_line += (
                f" · {labels['radar_signal']}: {meta['radar_signal_summary']}"
            )

        lines = [
            f'<a id="item-{index}"></a>',
            f"{'#' * heading_level} [{title}]({url}) \u2b50\ufe0f {score}/10",  # ⭐️
            "",
            summary,
            "",
            source_line,
        ]

        if background:
            lines.append("")
            lines.append(f"**{labels['background']}**: {background}")

        sources = meta.get("sources") or []
        if sources:
            items_html = "".join(f'<li><a href="{s["url"]}">{s["title"]}</a></li>\n' for s in sources)
            lines += [
                "",
                f'<details><summary>{labels["references"]}</summary>\n<ul>\n{items_html}\n</ul>\n</details>',
            ]

        if discussion:
            lines.append("")
            lines.append(f"**{labels['discussion']}**: {discussion}")

        if item.ai_tags:
            tags_str = ", ".join([f"`#{t}`" for t in item.ai_tags])
            lines.append("")
            lines.append(f"**{labels['tags']}**: {tags_str}")

        lines.append("")
        lines.append("---")

        return "\n".join(lines) + "\n\n"

    @staticmethod
    def _group_by_section(
        items: List[ContentItem],
        labels: dict,
    ) -> List[tuple[Optional[str], str, List[ContentItem]]]:
        """Group selected items by configured digest section in display order."""
        if not any(item.metadata.get("digest_section") for item in items):
            return [(None, "", items)]

        grouped: Dict[str, tuple[int, str, List[ContentItem]]] = {}
        for item in items:
            section_key = item.metadata.get("digest_section") or "__other__"
            section_name = item.metadata.get("digest_section_name") or (
                labels["uncategorized_section"]
                if section_key == "__other__"
                else section_key
            )
            order = int(item.metadata.get("digest_section_order", 999))
            if section_key not in grouped:
                grouped[section_key] = (order, str(section_name), [])
            grouped[section_key][2].append(item)

        ordered = sorted(grouped.items(), key=lambda entry: entry[1][0])
        return [
            (section_key, section_name, section_items)
            for section_key, (_, section_name, section_items) in ordered
        ]

    def _generate_empty_summary(self, date: str, total_fetched: int, labels: dict) -> str:
        """Generate summary when no high-scoring items were found."""
        return (
            f"# {labels['header']} - {date}\n\n"
            f"> {labels['empty_analyzed'].format(total=total_fetched)}\n\n"
            + labels["empty_body"]
        )
