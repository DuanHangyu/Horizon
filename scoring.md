---
layout: default
title: Scoring System
---

# Scoring System

After fetching content from all sources, Horizon uses an AI model to score each item on a 0-10 scale. This determines what appears in the daily summary.

## Pipeline

1. **Batch processing** — Items are scored in batches of 10 with a progress bar. Failed items receive a score of 0.
2. **Content preparation** — For each item, the content is truncated (800 chars if comments are present, 1000 otherwise) and engagement metrics are assembled from metadata (HN score, Reddit upvote ratio, etc.).
3. **AI analysis** — The prepared content is sent to the configured AI model (temperature 0.3) with a system prompt defining the scoring criteria.
4. **Response parsing** — The AI response is parsed as JSON (with fallbacks for code-block-wrapped JSON). Each item gets: `ai_score` (float), `ai_reason` (string), `ai_summary` (string), and `ai_tags` (list).
5. **Retry** — Failed AI calls are retried up to 3 times with exponential backoff (2-10 seconds).

## Scoring Scale

| Score | Tier | Description |
|-------|------|-------------|
| 9-10 | Groundbreaking | Major breakthroughs, paradigm shifts, major version releases, significant research breakthroughs |
| 7-8 | High Value | Important developments, technical deep-dives, novel approaches, insightful analysis, valuable tools |
| 5-6 | Interesting | Incremental improvements, useful tutorials, moderate community interest |
| 3-4 | Low Priority | Minor updates, common knowledge, overly promotional |
| 0-2 | Noise | Spam, off-topic, trivial updates |

## Scoring Factors

The AI evaluates each item based on:

- **Technical depth and novelty** — original ideas, new techniques, research contributions
- **Potential impact** — how broadly this affects software engineering, AI/ML, or systems research
- **Quality of writing/presentation** — clarity, structure, thoroughness
- **Community discussion** — insightful comments, diverse viewpoints, substantive debates
- **Engagement signals** — high upvotes/favorites paired with substantive discussion (not just raw numbers)

Engagement metadata is source-specific: HN provides score and comment count, Reddit provides upvote ratio and comment count.

### Radar scoring

AI products and breakout repositories use a two-layer score:

1. The AI rubric evaluates whether the item is genuinely an AI product/project,
   its novelty, practical founder/FDE value, documentation or demo evidence,
   and commercial or technical usefulness.
2. A deterministic evidence score evaluates auditable platform momentum:
   ranking, star velocity, votes, likes, comments, and cross-source agreement.

The final radar score is `75% semantic quality + 25% platform evidence`. An item
whose semantic score is below 7 can never be rescued by popularity. A repository
confirmed by two or three of GitHub Trending, Trendshift, and OSSInsight receives
a consensus bonus. The report shows the retained signal summary on the source
line so the ranking decision is inspectable.

## Filtering

After scoring, items are filtered by `filtering.ai_score_threshold` (default: `7.0`) and sorted by score descending. Optional balanced digest quotas are then applied before enrichment.

```json
{
  "filtering": {
    "ai_score_threshold": 7.0,
    "digest_backfill_score_threshold": 6.0,
    "time_window_hours": 24,
    "max_items": 20,
    "category_groups": {
      "ai": {
        "limit": 5,
        "categories": ["ai-news", "ai-tools", "machine-learning"],
        "source_limits": {"producthunt": 3, "show_hn": 3}
      }
    },
    "digest_sections": {
      "radar": {
        "name": "AI Products + OSS Radar",
        "limit": 10,
        "groups": ["ai"],
        "min_score": 7.0
      }
    }
  }
}
```

`category_groups` limits each configured category group independently.
`source_limits` is an optional hard cap per `radar_source`, including during
section backfill. `digest_sections.*.min_score` is a hard quality floor for that
section and is evaluated after radar calibration.
When `digest_sections` is configured, group limits become preferred allocations
inside the section and unused slots are backfilled by another group in that same
section. Section limits remain hard caps.
`max_items` caps the merged result. Both fields are optional; without them,
scoring and filtering behave as before.

Items scoring 9.0 or above are featured in the "Today's Highlights" section of the summary.

## Enrichment

Items that pass the score threshold and any balanced digest limits go through a second AI pass for enrichment (`src/ai/enricher.py`):

1. **Concept extraction** — AI identifies 1-3 technical concepts in the item that may need explanation.
2. **Web search** — Each concept is searched via DuckDuckGo to gather grounding context.
3. **Structured analysis** — The item content and search results are sent to AI, which produces:
   - `whats_new` — what specifically happened or changed
   - `why_it_matters` — significance and impact
   - `key_details` — notable technical details or caveats
   - `background` — background knowledge for readers without deep domain expertise

These fields are combined into a `detailed_summary` stored in the item's metadata and used in the final daily summary.
