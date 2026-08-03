"""Unit tests for daily summary rendering."""

import asyncio
from datetime import datetime, timezone

from src.ai.summarizer import DailySummarizer
from src.models import ContentItem, SourceType


def _run_async(coro):
    return asyncio.run(coro)


def _make_item(idx: int) -> ContentItem:
    item = ContentItem(
        id=f"rss:item-{idx}",
        source_type=SourceType.RSS,
        title=f"Important Item {idx}",
        url=f"https://example.com/items/{idx}",
        content="content",
        author="tester",
        published_at=datetime(2026, 4, 25, 8, 0, tzinfo=timezone.utc),
    )
    item.ai_score = 8.0
    item.ai_summary = f"Summary for item {idx}."
    item.ai_tags = ["AI", "News"]
    return item


def test_generate_webhook_overview_lists_items_without_full_details():
    summarizer = DailySummarizer()
    items = [_make_item(1), _make_item(2)]

    result = summarizer.generate_webhook_overview(
        items,
        date="2026-04-25",
        total_fetched=10,
        language="en",
    )

    assert "Selected 2 important items from 10 fetched items" in result
    assert "1. [Important Item 1](https://example.com/items/1)" in result
    assert "2. [Important Item 2](https://example.com/items/2)" in result
    assert "Summary for item 1." not in result


def test_generate_webhook_item_renders_single_item_detail():
    summarizer = DailySummarizer()

    result = summarizer.generate_webhook_item(
        _make_item(1),
        language="en",
        index=1,
        total=2,
    )

    assert result.startswith("Item 1/2")
    assert "## [Important Item 1](https://example.com/items/1)" in result
    assert "Summary for item 1." in result
    assert "**Tags**: `#AI`, `#News`" in result


def test_generate_webhook_item_includes_discussion_link_when_distinct():
    summarizer = DailySummarizer()
    item = _make_item(1)
    item.metadata["discussion_url"] = "https://news.ycombinator.com/item?id=1"

    result = summarizer.generate_webhook_item(
        item,
        language="en",
        index=1,
        total=1,
    )

    assert "tester · Apr 25, 08:00 · [Discussion](https://news.ycombinator.com/item?id=1)" in result


def test_generate_webhook_item_omits_discussion_link_when_same_as_item_url():
    summarizer = DailySummarizer()
    item = _make_item(1)
    item.metadata["discussion_url"] = item.url

    result = summarizer.generate_webhook_item(
        item,
        language="en",
        index=1,
        total=1,
    )

    assert "[Discussion](https://example.com/items/1)" not in result


def test_generate_webhook_item_uses_localized_discussion_label():
    summarizer = DailySummarizer()
    item = _make_item(1)
    item.metadata["discussion_url"] = "https://www.reddit.com/r/python/comments/abc123/test/"

    result = summarizer.generate_webhook_item(
        item,
        language="zh",
        index=1,
        total=1,
    )

    assert "[社区讨论](https://www.reddit.com/r/python/comments/abc123/test/)" in result


def test_generate_summary_zh_uses_localized_selection_header_and_numeric_date():
    summarizer = DailySummarizer()
    item = _make_item(1)

    result = _run_async(
        summarizer.generate_summary(
            [item],
            date="2026-04-25",
            total_fetched=10,
            language="zh",
        )
    )

    assert "> 从 10 条内容中筛选出 1 条重要资讯。" in result
    assert "rss · tester · 4月25日 08:00" in result
    assert "From 10 items" not in result
    assert "Apr 25, 08:00" not in result


def test_generate_summary_groups_items_into_digest_sections():
    summarizer = DailySummarizer()
    radar = _make_item(1)
    radar.metadata.update(
        {
            "digest_section": "radar",
            "digest_section_name": "第一部分：AI 产品 + 爆火开源项目雷达",
            "digest_section_order": 0,
        }
    )
    other = _make_item(2)
    other.metadata.update(
        {
            "digest_section": "other",
            "digest_section_name": "第二部分：其他 AI 前沿资讯",
            "digest_section_order": 1,
        }
    )

    result = _run_async(
        summarizer.generate_summary(
            [radar, other],
            date="2026-04-25",
            total_fetched=10,
            language="zh",
        )
    )

    assert "## 目录" in result
    assert "## 第一部分：AI 产品 + 爆火开源项目雷达（1）" in result
    assert "## 第二部分：其他 AI 前沿资讯（1）" in result
    assert "### [Important Item 1]" in result
    assert result.index("第一部分：AI 产品") < result.index("第二部分：其他 AI")


def test_generate_webhook_section_overviews_keeps_sections_separate():
    summarizer = DailySummarizer()
    radar = _make_item(1)
    radar.metadata.update(
        {
            "digest_section": "radar",
            "digest_section_name": "第一部分：AI 产品 + 爆火开源项目雷达",
            "digest_section_order": 0,
            "radar_source": "producthunt",
            "detailed_summary_zh": "这是用于飞书卡片的一句话中文摘要。",
        }
    )
    other = _make_item(2)
    other.metadata.update(
        {
            "digest_section": "other",
            "digest_section_name": "第二部分：其他 AI 前沿资讯",
            "digest_section_order": 1,
        }
    )

    results = summarizer.generate_webhook_section_overviews(
        [radar, other],
        date="2026-04-25",
        total_fetched=10,
        language="zh",
    )

    assert len(results) == 2
    assert results[0]["section_key"] == "radar"
    assert "Important Item 1" in results[0]["summary"]
    assert "摘要：这是用于飞书卡片的一句话中文摘要。" in results[0]["summary"]
    assert "Product Hunt" in results[0]["summary"]
    assert "Important Item 2" not in results[0]["summary"]
    assert results[1]["section_key"] == "other"
    assert "Important Item 2" in results[1]["summary"]
    assert "摘要：Summary for item 2." in results[1]["summary"]


def test_generate_webhook_section_overviews_truncates_long_summary():
    summarizer = DailySummarizer()
    item = _make_item(1)
    item.metadata["detailed_summary_zh"] = "摘" * 120

    results = summarizer.generate_webhook_section_overviews(
        [item],
        date="2026-04-25",
        total_fetched=1,
        language="zh",
    )

    rendered = results[0]["summary"]
    assert f"摘要：{'摘' * 79}…" in rendered
    assert "摘" * 80 + "…" not in rendered


def test_generate_webhook_section_overviews_splits_large_sections_without_drops():
    summarizer = DailySummarizer()
    items = []
    for index in range(1, 31):
        item = _make_item(index)
        item.title = f"Important Item {index} " + ("AI product " * 8)
        item.metadata.update(
            {
                "digest_section": "radar",
                "digest_section_name": "AI Products",
                "digest_section_order": 0,
            }
        )
        items.append(item)

    results = summarizer.generate_webhook_section_overviews(
        items,
        date="2026-04-25",
        total_fetched=50,
        language="en",
        max_bytes=4_000,
    )

    assert len(results) > 1
    assert all(len(result["summary"].encode("utf-8")) < 4_000 for result in results)
    combined = "\n".join(result["summary"] for result in results)
    assert "Important Item 1 " in combined
    assert "Important Item 30 " in combined


def test_generate_empty_summary_zh_uses_localized_analyzed_line():
    summarizer = DailySummarizer()

    result = _run_async(
        summarizer.generate_summary(
            [],
            date="2026-04-25",
            total_fetched=10,
            language="zh",
        )
    )

    assert "> 已分析 10 条内容，但没有达到重要性阈值的条目。" in result
    assert "Analyzed 10 items" not in result
