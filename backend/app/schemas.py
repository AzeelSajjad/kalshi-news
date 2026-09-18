from datetime import datetime

from pydantic import BaseModel


class MarketRef(BaseModel):
    ticker: str
    title: str
    direction: str
    confidence: float
    rationale: str
    yes_price: int | None
    volume: int | None
    close_time: datetime | None
    price_delta: int | None
    kalshi_url: str


class FeedItem(BaseModel):
    id: int
    title: str
    url: str
    author_name: str | None
    author_handle: str | None
    avatar_url: str | None
    source_kind: str
    category: str | None
    published_at: datetime
    cluster_size: int
    # The article's opening prose, stripped of markup at ingest. Carried on
    # the feed item so a card can show a snippet without a second request;
    # the frontend decides how much of it to show. None for X posts, whose
    # title already is the text.
    body: str | None
    markets: list[MarketRef]


class PostDetail(FeedItem):
    """Currently identical to FeedItem. Kept as its own response model
    because /api/posts/{id} is where any field too heavy for a 30-item page
    would go."""


class TrendingMarket(BaseModel):
    ticker: str
    title: str
    yes_price: int | None
    volume: int | None
    post_count: int = 0
    kalshi_url: str


class TrendingPage(BaseModel):
    by_volume: list[TrendingMarket]
    most_covered: list[TrendingMarket]


class FeedPage(BaseModel):
    items: list[FeedItem]
    next_cursor: str | None = None


class JobResult(BaseModel):
    job: str
    items_processed: int
