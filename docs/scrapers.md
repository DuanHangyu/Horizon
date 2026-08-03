---
layout: default
title: Source Scrapers
---

# Source Scrapers

Horizon fetches content from multiple source types. All scrapers inherit from `BaseScraper`, share an async HTTP client, and implement a `fetch(since)` method that returns a list of `ContentItem` objects. Sources are fetched concurrently via `asyncio.gather`.

## Hacker News

**File**: `src/scrapers/hackernews.py`

Uses the [Firebase HN API](https://hacker-news.firebaseio.com/v0):

- `GET /topstories.json` — fetches top story IDs
- `GET /item/{id}.json` — fetches story/comment details

Stories and their comments are fetched concurrently. For each story, the top 5 comments are included (deleted/dead comments excluded, HTML stripped, truncated at 500 chars).

**Config** (`sources.hackernews`):

```json
{
  "enabled": true,
  "fetch_top_stories": 30,
  "min_score": 100
}
```

- `fetch_top_stories` — number of top story IDs to fetch
- `min_score` — minimum HN points to include a story

**Extracted data**: title, URL (falls back to HN discussion URL), author, score, comment count, and top comment text.

## GitHub

**File**: `src/scrapers/github.py`

Uses the [GitHub REST API](https://api.github.com):

- `GET /users/{username}/events/public` — user activity events
- `GET /repos/{owner}/{repo}/releases` — repository releases

Two source types are supported:

- **`user_events`** — tracks push, create, release, public, and watch events for a user
- **`repo_releases`** — tracks new releases for a specific repository
- **`repo_search`** — discovers recently created repositories using a GitHub
  repository-search query, optional minimum stars, and a configurable lookback
  window; useful for new-project radar feeds

**Config** (`sources.github`, list of entries):

```json
{
  "type": "user_events",
  "username": "torvalds",
  "enabled": true
}
```

```json
{
  "type": "repo_releases",
  "owner": "golang",
  "repo": "go",
  "enabled": true
}
```

Recent repository discovery:

```json
{
  "type": "repo_search",
  "query": "topic:llm",
  "lookback_days": 30,
  "min_stars": 20,
  "max_items": 15,
  "category": "github-trending",
  "enabled": true
}
```

**Authentication**: Set `GITHUB_TOKEN` in your environment for higher rate limits (5000 req/hr vs 60 without).

## AI Product and Breakout OSS Radar

**Files**: `src/scrapers/trending.py`, `src/scrapers/product_radar.py`, and
`src/scrapers/hackernews.py`

The radar uses platform rankings as candidate-generation evidence instead of
treating a recent keyword-matched repository as "trending":

- **GitHub Trending** — public daily/weekly/monthly HTML ranking, including
  rank, total stars, forks, language, and stars gained in the selected period.
- **Trendshift** — official API when `TRENDSHIFT_API_TOKEN` is configured;
  otherwise its public JSON-LD ranking page. The public fallback exposes rank
  but fewer growth metrics.
- **OSSInsight** — recent star velocity and repository activity. Its current
  trending endpoint is public but not part of OSSInsight's documented stable
  API, so Horizon treats it as a corroborating signal.
- **Product Hunt** — official GraphQL API when `PRODUCTHUNT_TOKEN` is set;
  otherwise the public Atom feed. GraphQL provides daily rank, votes, comments,
  makers, and topics; RSS does not provide vote totals.
- **YC Launches** — the official launches page currently returns JSON with
  launch votes and company fields. Horizon filters for AI launches and checks
  company slugs against the visible YC AI company directory when available.
- **Hugging Face Spaces** — public Spaces metadata in the directory's default
  trending order, filtered by likes and recent activity.
- **Show HN** — the official `showstories.json` list plus item points, comments,
  and top-level discussion text.

All adapters emit `radar_signals`. When the same GitHub repository appears in
GitHub Trending, Trendshift, and OSSInsight, Horizon merges it by canonical URL
and preserves every signal rather than publishing three duplicate entries.

Product Hunt and Trendshift tokens are optional. Add these environment
variables for stable official APIs and richer metrics:

```dotenv
PRODUCTHUNT_TOKEN=...
TRENDSHIFT_API_TOKEN=ts_live_...
```

## RSS

**File**: `src/scrapers/rss.py`

Fetches any Atom/RSS feed using the `feedparser` library. Tries multiple date fields (`published`, `updated`, `created`) with fallback parsing.

**Config** (`sources.rss`, list of entries):

```json
{
  "name": "Simon Willison",
  "url": "https://simonwillison.net/atom/everything/",
  "enabled": true,
  "category": "ai-tools"
}
```

- `category` — optional tag for grouping (e.g., `"programming"`, `"microblog"`)

**Extracted data**: title, URL, author, content (from `summary`/`description`/`content` fields), feed name, category, and entry tags.

## Reddit

**File**: `src/scrapers/reddit.py`

Uses public, no-key Reddit endpoints. Subreddit listings and comments prefer `old.reddit.com` HTML because Reddit's unauthenticated JSON and RSS endpoints can intermittently block or fail:

- `GET https://old.reddit.com/r/{subreddit}/{sort}/` — subreddit posts
- `GET https://old.reddit.com/r/{subreddit}/comments/{post_id}/` — post comments
- `GET /r/{subreddit}/{sort}.json` — subreddit posts fallback
- `GET /user/{username}/submitted.json` — user submissions
- `GET /r/{subreddit}/comments/{post_id}.json` — post comments fallback
- `GET /r/{subreddit}/{sort}/.rss` — subreddit posts fallback when JSON is blocked

Subreddits and users are fetched concurrently. Comments are sorted by score, limited to the configured count, and exclude moderator-distinguished comments. Self-text is truncated at 1500 chars, comments at 500 chars.

**Config** (`sources.reddit`):

```json
{
  "enabled": true,
  "fetch_comments": 5,
  "subreddits": [
    {
      "subreddit": "MachineLearning",
      "sort": "hot",
      "fetch_limit": 25,
      "min_score": 10
    }
  ],
  "users": [
    {
      "username": "spez",
      "sort": "new",
      "fetch_limit": 10
    }
  ]
}
```

- `sort` — `hot`, `new`, `top`, or `rising` (subreddits); `hot` or `new` (users)
- `time_filter` — for `top`/`rising` sorts: `hour`, `day`, `week`, `month`, `year`, `all`
- `min_score` — minimum post score (subreddits only)

**Rate limiting**: Detects HTTP 429 responses on JSON requests, reads the `Retry-After` header, waits, and retries once. Uses browser-like request headers for no-key public access.

**Extracted data**: title, URL, author, score, upvote ratio, comment count, subreddit, flair, self-text, and top comments.

## OpenBB

**File**: `src/scrapers/openbb.py`

Uses the [OpenBB Platform](https://www.openbb.co/platform) Python SDK via `obb.news.company()` to fetch company news for one or more ticker watchlists.

The scraper imports `openbb` lazily. If the optional dependency is not installed, Horizon logs a warning and skips the source instead of failing the whole run.

**Config** (`sources.openbb`):

```json
{
  "enabled": true,
  "watchlists": [
    {
      "name": "megacaps",
      "symbols": ["AAPL", "MSFT", "NVDA"],
      "enabled": true,
      "provider": "yfinance",
      "fetch_limit": 20,
      "category": "equities"
    }
  ]
}
```

- `watchlists` — each enabled watchlist triggers one `news.company()` call per run
- `provider` — OpenBB provider name for that watchlist
- `symbols` — tickers fetched together for the same provider
- `fetch_limit` — maximum rows requested from the provider
- `category` — optional metadata tag stored on each item

Behavior:

- Wraps the synchronous OpenBB SDK in `asyncio.to_thread` so the event loop stays responsive
- Deduplicates duplicate news across watchlists by article URL
- Skips malformed rows, rows without URL/title/date, and items older than the current time window
- Keeps fetching other watchlists if one provider call fails

**Credentials**: provider-specific secrets are resolved by the OpenBB SDK from its own environment variables or settings file. Horizon does not pass those values directly.

**Extracted data**: title, URL, author, published time, article body/excerpt, watchlist name, provider, category, and symbol list.

## Twitter

**File**: `src/scrapers/twitter.py`

Uses the [Apify](https://apify.com) platform to bypass Twitter's anti-scraping measures. The actor `altimis~scweet` is called via the Apify REST API.

Flow:
1. POST to `/v2/acts/{actor_id}/runs` to trigger a run
2. Poll `/v2/actor-runs/{run_id}` until status is `SUCCEEDED` or a terminal failure
3. GET `/v2/datasets/{dataset_id}/items` to retrieve results

**Config** (`sources.twitter`):

```json
{
  "enabled": true,
  "users": ["karpathy", "ylecun"],
  "fetch_limit": 10,
  "fetch_reply_text": false,
  "max_replies_per_tweet": 3,
  "max_tweets_to_expand": 10,
  "reply_min_likes": 5,
  "actor_id": "altimis~scweet",
  "apify_token_env": "APIFY_TOKEN"
}
```

- `users` — Twitter screen names to monitor, without the `@` prefix
- `fetch_limit` — maximum tweets to fetch per run
- `fetch_reply_text` — when `true`, a second Apify run fetches reply bodies for each important tweet and appends them under `--- Top Comments ---` for AI analysis
- `max_replies_per_tweet` — maximum reply lines per tweet (sorted by engagement score)
- `max_tweets_to_expand` — cap on reply expansion runs per pipeline cycle, to control Apify credit usage
- `reply_min_likes` — minimum likes required for a reply to be included
- `actor_id` — Apify actor ID (default: `altimis~scweet`)
- `apify_token_env` — environment variable name containing the Apify API token

**Authentication**: Set `APIFY_TOKEN` in your `.env`. Get a token at [console.apify.com](https://console.apify.com/account/integrations).

**Extracted data**: tweet text, URL, author, publish time, likes, retweets, replies, views, and (optionally) reply-thread text appended under `--- Top Comments ---`.
