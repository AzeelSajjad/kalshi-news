from datetime import datetime, date
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer,
    Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base

EMBED_DIM = 1536


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))          # rss | x | reddit
    name: Mapped[str] = mapped_column(String(128))
    feed_url: Mapped[str | None] = mapped_column(String(512))
    handle: Mapped[str | None] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Cluster(Base):
    __tablename__ = "clusters"
    id: Mapped[int] = mapped_column(primary_key=True)
    representative_post_id: Mapped[int | None] = mapped_column(BigInteger)
    post_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_post_source_external"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str] = mapped_column(String(256))
    url: Mapped[str] = mapped_column(String(1024))
    author_name: Mapped[str | None] = mapped_column(String(128))
    author_handle: Mapped[str | None] = mapped_column(String(64))
    avatar_url: Mapped[str | None] = mapped_column(String(512))
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(32))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))
    cluster_id: Mapped[int | None] = mapped_column(ForeignKey("clusters.id"))
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[Source] = relationship()


class Market(Base):
    __tablename__ = "markets"
    ticker: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_ticker: Mapped[str | None] = mapped_column(String(128))
    series_ticker: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(Text)
    rules_summary: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    close_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    yes_price: Mapped[int | None] = mapped_column(Integer)      # cents, 0-100
    volume: Mapped[int | None] = mapped_column(BigInteger)
    text_hash: Mapped[str | None] = mapped_column(String(64))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class PostMarket(Base):
    __tablename__ = "post_markets"
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), primary_key=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("markets.ticker"), primary_key=True)
    direction: Mapped[str] = mapped_column(String(8))          # YES | NO
    confidence: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text)
    price_at_link: Mapped[int | None] = mapped_column(Integer)
    price_1h: Mapped[int | None] = mapped_column(Integer)
    price_24h: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    post: Mapped[Post] = relationship()
    market: Mapped[Market] = relationship()


class Subscriber(Base):
    __tablename__ = "subscribers"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    categories: Mapped[list[str] | None] = mapped_column(ARRAY(String(32)))
    unsub_token: Mapped[str] = mapped_column(String(64), unique=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class JobRun(Base):
    __tablename__ = "job_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16))            # running | ok | error
    items_processed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LlmSpend(Base):
    __tablename__ = "llm_spend"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    usd: Mapped[float] = mapped_column(Numeric(10, 6), default=0)
