"""Core data models for Horizon."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, HttpUrl, Field, field_validator


class SourceType(str, Enum):
    """Supported information source types."""

    GITHUB = "github"
    HACKERNEWS = "hackernews"
    RSS = "rss"
    REDDIT = "reddit"
    TELEGRAM = "telegram"
    TWITTER = "twitter"
    OPENBB = "openbb"
    OSSINSIGHT = "ossinsight"
    GDELT = "gdelt"
    GOOGLE_NEWS = "google_news"
    TRENDSHIFT = "trendshift"
    PRODUCTHUNT = "producthunt"
    YC = "yc"
    HUGGINGFACE = "huggingface"


class ContentItem(BaseModel):
    """Unified content item model from any source."""

    id: str  # Format: {source}:{subtype}:{native_id}
    source_type: SourceType
    title: str
    url: HttpUrl
    content: Optional[str] = None
    author: Optional[str] = None
    published_at: datetime
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # AI analysis results
    ai_score: Optional[float] = None  # 0-10 importance score
    ai_reason: Optional[str] = None
    ai_summary: Optional[str] = None
    ai_tags: List[str] = Field(default_factory=list)


class AIProvider(str, Enum):
    """Supported AI providers."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    AZURE = "azure"
    ALI = "ali"
    GEMINI = "gemini"
    DOUBAO = "doubao"
    MINIMAX = "minimax"
    DEEPSEEK = "deepseek"
    OLLAMA = "ollama"


# Default models and API key env vars for each provider
AI_PROVIDER_DEFAULTS = {
    AIProvider.ANTHROPIC: {
        "model": "claude-3-5-sonnet-20241022",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    AIProvider.OPENAI: {
        "model": "gpt-4",
        "api_key_env": "OPENAI_API_KEY",
    },
    AIProvider.AZURE: {
        "model": "gpt-4",
        "api_key_env": "AZURE_OPENAI_API_KEY",
    },
    AIProvider.ALI: {
        "model": "qwen-plus",
        "api_key_env": "DASHSCOPE_API_KEY",
    },
    AIProvider.GEMINI: {
        "model": "gemini-1.5-flash",
        "api_key_env": "GOOGLE_API_KEY",
    },
    AIProvider.DOUBAO: {
        "model": "doubao-pro-32k",
        "api_key_env": "DOUBAO_API_KEY",
    },
    AIProvider.MINIMAX: {
        "model": "MiniMax-Text-01",
        "api_key_env": "MINIMAX_API_KEY",
    },
    AIProvider.DEEPSEEK: {
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    AIProvider.OLLAMA: {
        "model": "llama3.1",
        "api_key_env": "",
    },
}


class AIConfig(BaseModel):
    """AI client configuration."""

    provider: AIProvider
    provider_chain: Optional[str] = None
    model: str
    base_url: Optional[str] = None
    api_key_env: str
    temperature: float = 0.3
    max_tokens: int = 4096
    throttle_sec: float = 0.0
    analysis_concurrency: int = 1
    enrichment_concurrency: int = 1
    languages: List[str] = Field(default_factory=lambda: ["en"])
    # Azure OpenAI specific; required when provider == AZURE
    azure_endpoint_env: Optional[str] = None
    api_version: Optional[str] = None


class GitHubSourceConfig(BaseModel):
    """GitHub source configuration."""

    type: str  # "user_events", "repo_releases", "repo_search", etc.
    username: Optional[str] = None
    owner: Optional[str] = None
    repo: Optional[str] = None
    query: Optional[str] = None
    lookback_days: int = Field(default=30, gt=0)
    min_stars: int = Field(default=0, ge=0)
    max_items: int = Field(default=10, gt=0, le=100)
    sort: str = "stars"
    order: str = "desc"
    category: Optional[str] = None
    enabled: bool = True


DEFAULT_AI_RADAR_KEYWORDS = [
    "ai",
    "artificial intelligence",
    "machine learning",
    "deep learning",
    "llm",
    "language model",
    "agent",
    "agentic",
    "mcp",
    "rag",
    "inference",
    "multimodal",
    "transformer",
    "diffusion",
    "embedding",
    "vector database",
    "copilot",
    "coding assistant",
]


class GitHubTrendingConfig(BaseModel):
    """GitHub Trending HTML source configuration."""

    enabled: bool = False
    period: str = "daily"  # daily, weekly, monthly
    languages: List[str] = Field(default_factory=lambda: [""])
    max_items: int = Field(default=30, gt=0, le=100)
    ai_only: bool = True
    keywords: List[str] = Field(default_factory=lambda: list(DEFAULT_AI_RADAR_KEYWORDS))
    category: Optional[str] = "github-trending"


class TrendshiftConfig(BaseModel):
    """Trendshift ranking source with optional official API credentials."""

    enabled: bool = False
    period: str = "daily"
    max_items: int = Field(default=30, gt=0, le=100)
    api_token_env: str = "TRENDSHIFT_API_TOKEN"
    ai_only: bool = True
    keywords: List[str] = Field(default_factory=lambda: list(DEFAULT_AI_RADAR_KEYWORDS))
    category: Optional[str] = "github-trending"


class ProductHuntConfig(BaseModel):
    """Product Hunt launch source, using GraphQL with an RSS fallback."""

    enabled: bool = False
    max_items: int = Field(default=20, gt=0, le=100)
    api_token_env: str = "PRODUCTHUNT_TOKEN"
    feed_url: str = "https://www.producthunt.com/feed"
    ai_only: bool = True
    keywords: List[str] = Field(default_factory=lambda: list(DEFAULT_AI_RADAR_KEYWORDS))
    category: Optional[str] = "startup-products"


class YCProductsConfig(BaseModel):
    """YC Launches source, optionally cross-checked against the YC AI directory."""

    enabled: bool = False
    max_items: int = Field(default=20, gt=0, le=100)
    ai_only: bool = True
    validate_ai_directory: bool = True
    category: Optional[str] = "startup-products"


class HuggingFaceSpacesConfig(BaseModel):
    """Trending public Hugging Face Spaces source configuration."""

    enabled: bool = False
    max_items: int = Field(default=20, gt=0, le=100)
    min_likes: int = Field(default=10, ge=0)
    max_age_days: int = Field(default=30, gt=0)
    category: Optional[str] = "ai-products"


class HackerNewsConfig(BaseModel):
    """Hacker News configuration."""

    enabled: bool = True
    fetch_top_stories: int = 30
    min_score: int = 100


class ShowHNConfig(BaseModel):
    """Dedicated Show HN product discovery feed."""

    enabled: bool = False
    fetch_top_stories: int = Field(default=50, gt=0, le=500)
    min_score: int = Field(default=10, ge=0)
    ai_only: bool = True
    keywords: List[str] = Field(default_factory=lambda: list(DEFAULT_AI_RADAR_KEYWORDS))
    category: Optional[str] = "startup-products"


class RSSSourceConfig(BaseModel):
    """RSS feed source configuration."""

    name: str
    url: HttpUrl
    enabled: bool = True
    category: Optional[str] = None


class RedditSubredditConfig(BaseModel):
    """Configuration for monitoring a specific subreddit."""

    subreddit: str
    enabled: bool = True
    sort: str = "hot"  # hot, new, top, rising
    time_filter: str = (
        "day"  # hour, day, week, month, year, all (only for top/controversial)
    )
    fetch_limit: int = 25
    min_score: int = 10


class RedditUserConfig(BaseModel):
    """Configuration for monitoring a specific Reddit user."""

    username: str  # without u/ prefix
    enabled: bool = True
    sort: str = "new"
    fetch_limit: int = 10


class RedditConfig(BaseModel):
    """Reddit source configuration."""

    enabled: bool = True
    subreddits: List[RedditSubredditConfig] = Field(default_factory=list)
    users: List[RedditUserConfig] = Field(default_factory=list)
    fetch_comments: int = 5  # top comments per post, 0 to disable


class TelegramChannelConfig(BaseModel):
    """Configuration for monitoring a specific Telegram channel."""

    channel: str  # channel username, e.g. "zaihuapd"
    enabled: bool = True
    fetch_limit: int = 20


class TelegramConfig(BaseModel):
    """Telegram source configuration."""

    enabled: bool = True
    channels: List[TelegramChannelConfig] = Field(default_factory=list)


class TwitterConfig(BaseModel):
    """Twitter source configuration.

    Two modes are supported:
    - "apify": Use Apify scweet actor (requires APIFY_TOKEN, more reliable)
    - "playwright": Use Playwright + browser cookies (free, no token needed)
    """

    enabled: bool = True
    mode: str = "apify"  # "apify" or "playwright"
    users: List[str] = Field(default_factory=list)
    fetch_limit: int = 10
    fetch_reply_text: bool = False
    max_replies_per_tweet: int = 3
    max_tweets_to_expand: int = 10
    reply_min_likes: int = 0
    # Apify settings (used when mode == "apify")
    apify_token_env: str = "APIFY_TOKEN"
    actor_id: str = "altimis~scweet"
    # Playwright settings (used when mode == "playwright")
    cookie_dir: str = "data"
    cookie_file_pattern: str = "x_cookies_*.json"


class OpenBBWatchlist(BaseModel):
    """A named watchlist of tickers fetched from one OpenBB provider.

    Each watchlist produces one news.company() call per run, so group
    symbols by provider rather than creating one watchlist per symbol.
    """

    name: str
    symbols: List[str] = Field(default_factory=list)
    enabled: bool = True
    provider: str = "yfinance"
    fetch_limit: int = 20
    category: Optional[str] = None


class OpenBBConfig(BaseModel):
    """OpenBB Platform source configuration.

    Uses the installed `openbb` SDK to fetch news and filings for a set of
    tickers. The SDK is an optional dependency; if it is not installed the
    scraper will no-op with a console warning rather than crash the run.

    Provider credentials (FMP, Benzinga, Polygon, Intrinio, Tiingo, etc.)
    are resolved by openbb from environment variables / its own user
    settings file, so Horizon does not need to pass them explicitly.
    """

    enabled: bool = True
    watchlists: List[OpenBBWatchlist] = Field(default_factory=list)
    fetch_filings: bool = False
    filings_provider: str = "sec"


class OSSInsightConfig(BaseModel):
    """OSS Insight trending repos source configuration.

    Pulls top star-gain repositories from the OSS Insight public API and
    emits them as ContentItems. Optional `keywords` filter limits results
    to repos whose description, repo name, or collection names contain at
    least one of the listed substrings (case-insensitive). Leave
    `keywords` empty to ingest everything trending in the configured
    languages.
    """

    enabled: bool = False
    period: str = "past_24_hours"  # past_24_hours, past_28_days
    languages: List[str] = Field(
        default_factory=lambda: ["All", "Python", "TypeScript"]
    )
    keywords: List[str] = Field(default_factory=list)
    min_stars: int = 5
    max_items: int = 30
    category: Optional[str] = None


class GDELTConfig(BaseModel):
    """GDELT 2.0 DOC API source configuration.

    Queries the key-less GDELT DOC API
    (https://api.gdeltproject.org/api/v2/doc/doc) for recent news articles
    matching a search query and emits them as ContentItems. No API key is
    required. The DOC API caps results at 250 records per request, so keep
    `max_records` modest.
    """

    enabled: bool = False
    query: str = "artificial intelligence"
    mode: str = "ArtList"
    max_records: int = 75  # GDELT DOC API caps at 250; keep modest
    timespan: Optional[str] = None  # e.g. "24h"; overrides since-derived window
    language: Optional[str] = None  # sourcelang filter, e.g. "english"; None = no filter
    country: Optional[str] = None  # sourcecountry filter; None = no filter
    category: Optional[str] = None  # Horizon category label for downstream grouping


class GoogleNewsConfig(BaseModel):
    """Google News RSS search source configuration.

    Builds Google News RSS search URLs
    (https://news.google.com/rss/search) for a query and parses the
    resulting feed via feedparser. No API key is required.
    """

    enabled: bool = False
    query: str = "artificial intelligence"
    language: str = "en"  # hl
    country: str = "US"  # gl
    ceid: Optional[str] = None  # when None scraper derives it as "{country}:{language}"
    max_results: int = 100  # cap ~100
    category: Optional[str] = None


class SourcesConfig(BaseModel):
    """All sources configuration."""

    github: List[GitHubSourceConfig] = Field(default_factory=list)
    github_trending: GitHubTrendingConfig = Field(default_factory=GitHubTrendingConfig)
    trendshift: TrendshiftConfig = Field(default_factory=TrendshiftConfig)
    hackernews: HackerNewsConfig = Field(default_factory=HackerNewsConfig)
    show_hn: ShowHNConfig = Field(default_factory=ShowHNConfig)
    rss: List[RSSSourceConfig] = Field(default_factory=list)
    producthunt: ProductHuntConfig = Field(default_factory=ProductHuntConfig)
    yc_products: YCProductsConfig = Field(default_factory=YCProductsConfig)
    huggingface_spaces: HuggingFaceSpacesConfig = Field(
        default_factory=HuggingFaceSpacesConfig
    )
    reddit: RedditConfig = Field(default_factory=RedditConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    twitter: Optional[TwitterConfig] = None
    openbb: Optional[OpenBBConfig] = None
    ossinsight: OSSInsightConfig = Field(default_factory=OSSInsightConfig)
    gdelt: Optional[GDELTConfig] = None
    google_news: Optional[GoogleNewsConfig] = None


class WebhookConfig(BaseModel):
    """Webhook notification configuration."""

    url_env: Optional[str] = (
        None  # Environment variable name containing the webhook URL
    )
    request_body: Optional[Union[str, dict, list]] = (
        None  # POST body: real JSON object or string with #{key} placeholders; if empty, will use GET
    )
    headers: Optional[str] = None  # Custom headers, "Key: Value" per line
    delivery: str = "summary"  # summary, summary_and_items, or section_overviews
    overview_position: str = "first"  # For summary_and_items: first, or last
    platform: str = "generic"  # generic, feishu, lark, dingtalk, slack, discord
    layout: str = "markdown"  # markdown, or collapsible
    fallback_layout: str = (
        "markdown"  # Layout to use when the requested layout is unsupported
    )
    languages: Optional[List[str]] = (
        None  # Optional language filter for webhook delivery; defaults to all AI languages
    )
    section_max_bytes: int = Field(default=14_000, ge=4_000, le=18_000)
    send_interval_sec: float = Field(default=0.0, ge=0.0, le=60.0)
    enabled: bool = False

    @field_validator("delivery")
    @classmethod
    def validate_delivery(cls, v: str) -> str:
        allowed = {"summary", "summary_and_items", "section_overviews"}
        if v not in allowed:
            raise ValueError(f"webhook.delivery must be one of {allowed}, got '{v}'")
        return v

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        allowed = {"generic", "feishu", "lark", "dingtalk", "slack", "discord"}
        if v not in allowed:
            raise ValueError(f"webhook.platform must be one of {allowed}, got '{v}'")
        return v

    @field_validator("layout")
    @classmethod
    def validate_layout(cls, v: str) -> str:
        allowed = {"markdown", "collapsible"}
        if v not in allowed:
            raise ValueError(f"webhook.layout must be one of {allowed}, got '{v}'")
        return v

    @field_validator("fallback_layout")
    @classmethod
    def validate_fallback_layout(cls, v: str) -> str:
        allowed = {"markdown", "collapsible"}
        if v not in allowed:
            raise ValueError(
                f"webhook.fallback_layout must be one of {allowed}, got '{v}'"
            )
        return v

    @field_validator("overview_position")
    @classmethod
    def validate_overview_position(cls, v: str) -> str:
        allowed = {"first", "last"}
        if v not in allowed:
            raise ValueError(
                f"webhook.overview_position must be one of {allowed}, got '{v}'"
            )
        return v


class EmailConfig(BaseModel):
    """Email configuration for updates/subscriptions."""

    imap_server: str
    imap_port: int = 993
    imap_enabled: bool = True
    smtp_server: str
    smtp_port: int = 465
    smtp_username: Optional[str] = None
    email_address: str
    password_env: str = "EMAIL_PASSWORD"
    sender_name: str = "Horizon Daily"
    subscribe_keyword: str = "SUBSCRIBE"
    unsubscribe_keyword: str = "UNSUBSCRIBE"
    enabled: bool = False


class CategoryGroupConfig(BaseModel):
    """A quota group containing one or more source categories."""

    name: Optional[str] = None
    limit: int = Field(gt=0)
    categories: List[str] = Field(min_length=1)
    source_limits: Dict[str, int] = Field(default_factory=dict)

    @field_validator("source_limits")
    @classmethod
    def validate_source_limits(cls, value: Dict[str, int]) -> Dict[str, int]:
        if any(limit <= 0 for limit in value.values()):
            raise ValueError("category group source limits must be positive")
        return value


class DigestSectionConfig(BaseModel):
    """A top-level digest section made up of one or more quota groups.

    Group limits are treated as preferred allocations inside a section. Any
    unused allocation is backfilled by the highest-scoring remaining items
    from another group in the same section, up to the section limit.
    """

    name: Optional[str] = None
    limit: int = Field(gt=0)
    groups: List[str] = Field(min_length=1)
    min_score: Optional[float] = Field(default=None, ge=0, le=10)


class FilteringConfig(BaseModel):
    """Content filtering configuration."""

    ai_score_threshold: float = 7.0
    digest_backfill_score_threshold: Optional[float] = Field(
        default=None,
        ge=0,
        le=10,
    )
    time_window_hours: int = 24
    max_items: Optional[int] = Field(default=None, gt=0)
    category_groups: Dict[str, CategoryGroupConfig] = Field(default_factory=dict)
    digest_sections: Dict[str, DigestSectionConfig] = Field(default_factory=dict)
    default_group: str = "other"
    default_group_limit: Optional[int] = Field(default=None, gt=0)
    default_section: Optional[str] = None


class Config(BaseModel):
    """Main configuration model."""

    version: str = "1.0"
    ai: AIConfig
    sources: SourcesConfig
    filtering: FilteringConfig
    email: Optional[EmailConfig] = None
    webhook: Optional[WebhookConfig] = None
