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
    markets: list[MarketRef]


class PostDetail(FeedItem):
    body: str | None


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
