import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from rich.console import Console

from src.models import (
    AIConfig,
    CategoryGroupConfig,
    Config,
    ContentItem,
    DigestSectionConfig,
    FilteringConfig,
    SourceType,
    SourcesConfig,
)
from src.orchestrator import HorizonOrchestrator


def make_item(item_id: str, score: float, category: str | None) -> ContentItem:
    metadata = {"category": category} if category is not None else {}
    return ContentItem(
        id=item_id,
        source_type=SourceType.RSS,
        title=item_id,
        url=f"https://example.com/{item_id}",
        published_at=datetime.now(timezone.utc),
        ai_score=score,
        metadata=metadata,
    )


def make_orchestrator(filtering: FilteringConfig) -> HorizonOrchestrator:
    orchestrator = HorizonOrchestrator.__new__(HorizonOrchestrator)
    orchestrator.config = SimpleNamespace(filtering=filtering)
    orchestrator.console = Console(record=True)
    return orchestrator


def test_unconfigured_balanced_digest_preserves_old_behavior() -> None:
    items = [make_item("lower", 7.0, "ai"), make_item("higher", 9.0, "finance")]
    result = make_orchestrator(FilteringConfig()).apply_balanced_digest(items)

    assert result.enabled is False
    assert result.items is items


def test_category_groups_apply_limits_and_default_group_limit() -> None:
    filtering = FilteringConfig(
        category_groups={
            "ai": CategoryGroupConfig(limit=2, categories=["ai", "ml"]),
            "finance": CategoryGroupConfig(limit=1, categories=["finance"]),
        },
        default_group_limit=1,
    )
    items = [
        make_item("ai-low", 7.0, "ai"),
        make_item("finance-low", 6.0, "finance"),
        make_item("other-high", 9.5, "world"),
        make_item("ai-high", 9.0, "ml"),
        make_item("finance-high", 8.5, "finance"),
        make_item("ai-mid", 8.0, "ai"),
        make_item("other-low", 5.0, None),
    ]

    result = make_orchestrator(filtering).apply_balanced_digest(items)

    assert [item.id for item in result.items] == [
        "other-high",
        "ai-high",
        "finance-high",
        "ai-mid",
    ]
    assert result.group_counts == {"other": 1, "ai": 2, "finance": 1}


def test_max_items_applies_after_group_limits() -> None:
    filtering = FilteringConfig(
        max_items=2,
        category_groups={
            "ai": CategoryGroupConfig(limit=2, categories=["ai"]),
            "finance": CategoryGroupConfig(limit=2, categories=["finance"]),
        },
    )
    items = [
        make_item("finance", 8.0, "finance"),
        make_item("ai-top", 10.0, "ai"),
        make_item("ai-second", 9.0, "ai"),
    ]

    result = make_orchestrator(filtering).apply_balanced_digest(items)

    assert [item.id for item in result.items] == ["ai-top", "ai-second"]
    assert result.group_counts == {"ai": 2}


def test_max_items_works_without_category_groups() -> None:
    filtering = FilteringConfig(max_items=1)
    items = [make_item("lower", 7.0, None), make_item("higher", 9.0, None)]

    result = make_orchestrator(filtering).apply_balanced_digest(items)

    assert [item.id for item in result.items] == ["higher"]


def test_digest_section_backfills_unused_group_allocation() -> None:
    filtering = FilteringConfig(
        max_items=4,
        category_groups={
            "products": CategoryGroupConfig(limit=2, categories=["product"]),
            "github": CategoryGroupConfig(limit=2, categories=["github"]),
        },
        digest_sections={
            "radar": DigestSectionConfig(
                name="AI Products + OSS Radar",
                limit=4,
                groups=["products", "github"],
            )
        },
    )
    items = [
        make_item("product", 9.5, "product"),
        make_item("github-1", 9.0, "github"),
        make_item("github-2", 8.5, "github"),
        make_item("github-3", 8.0, "github"),
        make_item("github-4", 7.5, "github"),
    ]

    result = make_orchestrator(filtering).apply_balanced_digest(items)

    assert [item.id for item in result.items] == [
        "product",
        "github-1",
        "github-2",
        "github-3",
    ]
    assert result.group_counts == {"products": 1, "github": 3}
    assert result.section_counts == {"radar": 4}
    assert result.items[0].metadata["digest_section"] == "radar"
    assert result.items[0].metadata["digest_section_name"] == "AI Products + OSS Radar"


def test_digest_sections_do_not_backfill_from_another_section() -> None:
    filtering = FilteringConfig(
        category_groups={
            "radar": CategoryGroupConfig(limit=2, categories=["radar"]),
            "other": CategoryGroupConfig(limit=2, categories=["other"]),
        },
        digest_sections={
            "radar_section": DigestSectionConfig(limit=2, groups=["radar"]),
            "other_section": DigestSectionConfig(limit=2, groups=["other"]),
        },
    )
    items = [
        make_item("radar-only", 9.0, "radar"),
        make_item("other-1", 8.5, "other"),
        make_item("other-2", 8.0, "other"),
        make_item("other-3", 7.5, "other"),
    ]

    result = make_orchestrator(filtering).apply_balanced_digest(items)

    assert [item.id for item in result.items] == ["radar-only", "other-1", "other-2"]
    assert result.section_counts == {"radar_section": 1, "other_section": 2}


def test_digest_section_min_score_and_source_caps_are_hard_limits() -> None:
    filtering = FilteringConfig(
        category_groups={
            "products": CategoryGroupConfig(
                limit=4,
                categories=["product"],
                source_limits={"producthunt": 1},
            ),
        },
        digest_sections={
            "radar": DigestSectionConfig(
                limit=4,
                groups=["products"],
                min_score=7.0,
            )
        },
    )
    ph_top = make_item("ph-top", 9.0, "product")
    ph_top.metadata["radar_source"] = "producthunt"
    ph_second = make_item("ph-second", 8.5, "product")
    ph_second.metadata["radar_source"] = "producthunt"
    yc = make_item("yc", 8.0, "product")
    yc.metadata["radar_source"] = "yc_launches"
    below = make_item("below", 6.9, "product")
    below.metadata["radar_source"] = "yc_launches"

    result = make_orchestrator(filtering).apply_balanced_digest(
        [ph_top, ph_second, yc, below]
    )

    assert [item.id for item in result.items] == ["ph-top", "yc"]


def test_cross_source_merge_preserves_all_radar_signals() -> None:
    orchestrator = make_orchestrator(FilteringConfig())
    github = make_item("github", 8.0, "github")
    github.url = "https://github.com/acme/agent"
    github.metadata["radar_signals"] = [
        {"source": "github_trending", "rank": 1}
    ]
    trendshift = make_item("trendshift", 8.0, "github")
    trendshift.url = "https://github.com/acme/agent/"
    trendshift.source_type = SourceType.TRENDSHIFT
    trendshift.metadata["radar_signals"] = [
        {"source": "trendshift", "rank": 2}
    ]

    merged = orchestrator.merge_cross_source_duplicates([github, trendshift])

    assert len(merged) == 1
    assert {signal["source"] for signal in merged[0].metadata["radar_signals"]} == {
        "github_trending",
        "trendshift",
    }
    assert merged[0].metadata["radar_source_count"] == 2


def test_duplicate_category_warns_and_first_group_wins() -> None:
    filtering = FilteringConfig(
        category_groups={
            "first": CategoryGroupConfig(limit=1, categories=["shared"]),
            "second": CategoryGroupConfig(limit=2, categories=["shared"]),
        }
    )
    orchestrator = make_orchestrator(filtering)

    result = orchestrator.apply_balanced_digest(
        [make_item("top", 9.0, "shared"), make_item("second", 8.0, "shared")]
    )

    assert [item.id for item in result.items] == ["top"]
    assert result.duplicate_categories == ["shared"]
    assert "using 'first'" in orchestrator.console.export_text()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_items": 0},
        {"default_group_limit": 0},
        {"category_groups": {"ai": {"limit": 0, "categories": ["ai"]}}},
        {"category_groups": {"ai": {"limit": 1, "categories": []}}},
        {"digest_sections": {"radar": {"limit": 0, "groups": ["ai"]}}},
        {"digest_sections": {"radar": {"limit": 1, "groups": []}}},
        {"digest_backfill_score_threshold": 11},
    ],
)
def test_balanced_digest_config_rejects_non_positive_or_empty_limits(kwargs) -> None:
    with pytest.raises(ValidationError):
        FilteringConfig(**kwargs)


def test_run_applies_balanced_digest_before_enrichment(tmp_path, monkeypatch) -> None:
    config = Config(
        ai=AIConfig(
            provider="openai",
            model="test",
            api_key_env="TEST_API_KEY",
            languages=[],
        ),
        sources=SourcesConfig(),
        filtering=FilteringConfig(
            ai_score_threshold=7.0,
            max_items=1,
            category_groups={
                "ai": CategoryGroupConfig(limit=1, categories=["ai"]),
                "finance": CategoryGroupConfig(limit=1, categories=["finance"]),
            },
        ),
    )
    storage = SimpleNamespace()
    orchestrator = HorizonOrchestrator(config, storage)
    items = [
        make_item("ai", 9.0, "ai"),
        make_item("finance", 8.0, "finance"),
        make_item("below-threshold", 6.0, "ai"),
    ]
    enriched_ids: list[str] = []

    async def fetch_all_sources(since):  # type: ignore[no-untyped-def]
        return items

    async def analyze_content(input_items):  # type: ignore[no-untyped-def]
        return input_items

    async def merge_topic_duplicates(input_items):  # type: ignore[no-untyped-def]
        return input_items

    async def expand_twitter_discussion(input_items):  # type: ignore[no-untyped-def]
        return None

    async def enrich_important_items(input_items):  # type: ignore[no-untyped-def]
        enriched_ids.extend(item.id for item in input_items)

    monkeypatch.setattr(orchestrator, "fetch_all_sources", fetch_all_sources)
    monkeypatch.setattr(orchestrator, "_analyze_content", analyze_content)
    monkeypatch.setattr(orchestrator, "merge_topic_duplicates", merge_topic_duplicates)
    monkeypatch.setattr(orchestrator, "_expand_twitter_discussion", expand_twitter_discussion)
    monkeypatch.setattr(orchestrator, "_enrich_important_items", enrich_important_items)
    monkeypatch.chdir(tmp_path)

    asyncio.run(orchestrator.run())

    assert enriched_ids == ["ai"]


def test_run_uses_lower_score_floor_only_for_digest_backfill(tmp_path, monkeypatch) -> None:
    config = Config(
        ai=AIConfig(
            provider="openai",
            model="test",
            api_key_env="TEST_API_KEY",
            languages=[],
        ),
        sources=SourcesConfig(),
        filtering=FilteringConfig(
            ai_score_threshold=7.0,
            digest_backfill_score_threshold=6.0,
            max_items=2,
            category_groups={
                "ai": CategoryGroupConfig(limit=2, categories=["ai"]),
            },
            digest_sections={
                "radar": DigestSectionConfig(limit=2, groups=["ai"]),
            },
        ),
    )
    orchestrator = HorizonOrchestrator(config, SimpleNamespace())
    items = [
        make_item("primary", 8.0, "ai"),
        make_item("backfill", 6.0, "ai"),
        make_item("too-low", 5.5, "ai"),
    ]
    enriched_ids: list[str] = []

    async def fetch_all_sources(since):  # type: ignore[no-untyped-def]
        return items

    async def passthrough(input_items):  # type: ignore[no-untyped-def]
        return input_items

    async def no_twitter(input_items):  # type: ignore[no-untyped-def]
        return None

    async def enrich(input_items):  # type: ignore[no-untyped-def]
        enriched_ids.extend(item.id for item in input_items)

    monkeypatch.setattr(orchestrator, "fetch_all_sources", fetch_all_sources)
    monkeypatch.setattr(orchestrator, "_analyze_content", passthrough)
    monkeypatch.setattr(orchestrator, "merge_topic_duplicates", passthrough)
    monkeypatch.setattr(orchestrator, "_expand_twitter_discussion", no_twitter)
    monkeypatch.setattr(orchestrator, "_enrich_important_items", enrich)
    monkeypatch.chdir(tmp_path)

    asyncio.run(orchestrator.run())

    assert enriched_ids == ["primary", "backfill"]
