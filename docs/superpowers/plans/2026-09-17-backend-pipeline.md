# Kalshi News Backend Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend that ingests news articles and X posts, links each one to the Kalshi markets it bears on, tracks how prices moved afterward, and serves it all over a read API.

**Architecture:** Four stages connected only through Postgres, never by direct calls — Kalshi sync, ingestors, linker, impact tracker. Each stage is an idempotent job invoked by an authenticated HTTP endpoint that GitHub Actions cron calls on a schedule. The linker is the core: pgvector narrows the market catalog to ten candidates, then one Claude Haiku call confirms relevance and produces a YES/NO direction with a rationale.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 + Alembic, Neon Postgres + pgvector, httpx, feedparser, Anthropic SDK (Claude Haiku), OpenAI SDK (embeddings), pytest + respx.

**Spec:** `docs/superpowers/specs/2026-09-17-kalshi-news-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- Python 3.11. All backend code lives under `backend/`.
- Embeddings: OpenAI `text-embedding-3-small`, **1536 dimensions**. Never change the dimension without a migration.
- LLM: Anthropic model id **`claude-haiku-4-5-20251001`**.
- Kalshi REST base URL: `https://external-api.kalshi.com/trade-api/v2`. Public endpoints only — never send auth headers, never call `/portfolio`.
- X hydration: `https://publish.twitter.com/oembed` only. No scraping, no headless browsers, no logged-in sessions.
- Every job must be idempotent. Re-running a job must never duplicate rows or double-charge an API.
- Linking precision is weighted over recall. A missing tag is invisible; a wrong tag looks broken. Target ≥0.85 precision on the golden set.
- Hard daily LLM spend cap enforced in the database. When the cap is hit, linking pauses and posts render untagged — never crash.
- No test may make a live external API call. All external HTTP is mocked with `respx`.
- All timestamps are stored timezone-aware in UTC.
- Commit after every task with a conventional-commit message.

---

### Task 1: Project scaffolding and CI

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_config.py`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: `app.config.Settings` — a pydantic-settings class with fields `database_url: str`, `anthropic_api_key: str`, `openai_api_key: str`, `job_token: str`, `daily_llm_budget_usd: float = 1.0`. Module-level `get_settings() -> Settings` (cached).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_config.py
import os
from app.config import get_settings


def test_settings_read_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai-test")
    monkeypatch.setenv("JOB_TOKEN", "secret")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.database_url == "postgresql://u:p@localhost/db"
    assert settings.job_token == "secret"
    assert settings.daily_llm_budget_usd == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 3: Write minimal implementation**

```toml
# backend/pyproject.toml
[project]
name = "kalshi-news-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "sqlalchemy>=2.0",
    "alembic>=1.14",
    "psycopg[binary]>=3.2",
    "pgvector>=0.3",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "httpx>=0.27",
    "feedparser>=6.0",
    "anthropic>=0.40",
    "openai>=1.54",
    "tenacity>=9.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24", "respx>=0.21", "ruff>=0.7"]

[tool.pytest.ini_options]
pythonpath = ["."]
asyncio_mode = "auto"
```

```python
# backend/app/config.py
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    job_token: str = ""
    daily_llm_budget_usd: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Create empty `backend/app/__init__.py` and `backend/tests/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pip install -e ".[dev]" && python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Add CI workflow**

```yaml
# .github/workflows/ci.yml
name: CI
on:
  push:
    branches: [main]
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: kalshi_news_test
        options: >-
          --health-cmd pg_isready --health-interval 10s
          --health-timeout 5s --health-retries 5
        ports: ["5432:5432"]
    env:
      DATABASE_URL: postgresql+psycopg://postgres:postgres@localhost:5432/kalshi_news_test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e "./backend[dev]"
      - run: cd backend && ruff check .
      - run: cd backend && python -m pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/ .github/workflows/ci.yml
git commit -m "chore: scaffold backend package and CI"
```

---

### Task 2: Database schema and migrations

**Files:**
- Create: `backend/app/db.py`
- Create: `backend/app/models.py`
- Create: `backend/alembic.ini`
- Create: `backend/migrations/env.py`
- Create: `backend/migrations/versions/0001_initial.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_models.py`

**Interfaces:**
- Consumes: `app.config.get_settings`.
- Produces:
  - `app.db.Base` (DeclarativeBase), `app.db.engine`, `app.db.SessionLocal`, `app.db.get_session()` context manager.
  - `app.models`: `Source`, `Post`, `Cluster`, `Market`, `PostMarket`, `Subscriber`, `JobRun`, `LlmSpend`.
  - Column names exactly as written below — every later task depends on them.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/conftest.py
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.config import get_settings
from app.db import Base


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(get_settings().database_url)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.rollback()
    for table in reversed(Base.metadata.sorted_tables):
        s.execute(table.delete())
    s.commit()
    s.close()
```

```python
# backend/tests/test_models.py
from datetime import datetime, timezone
from app.models import Source, Post, Market, PostMarket


def test_post_market_link_round_trips(session):
    source = Source(kind="rss", name="Reuters", feed_url="https://r.com/rss", category="Economics")
    session.add(source)
    session.flush()

    post = Post(
        source_id=source.id,
        external_id="abc123",
        url="https://r.com/a",
        author_name="Reuters",
        title="Powell signals cut",
        body="Officials see room to ease.",
        published_at=datetime(2026, 9, 17, tzinfo=timezone.utc),
        embedding=[0.1] * 1536,
    )
    market = Market(
        ticker="FED-26SEP",
        event_ticker="FED",
        title="Fed cuts rates in September?",
        rules_summary="Resolves YES if the target rate is lowered.",
        category="Economics",
        status="open",
        close_time=datetime(2026, 9, 30, tzinfo=timezone.utc),
        yes_price=72,
        volume=5100000,
        text_hash="deadbeef",
        embedding=[0.2] * 1536,
    )
    session.add_all([post, market])
    session.flush()

    session.add(PostMarket(
        post_id=post.id, ticker=market.ticker, direction="YES",
        confidence=0.86, rationale="Powell signaled a cut.", price_at_link=72,
    ))
    session.commit()

    link = session.query(PostMarket).one()
    assert link.direction == "YES"
    assert link.post.title == "Powell signals cut"
    assert link.market.ticker == "FED-26SEP"


def test_post_external_id_is_unique_per_source(session):
    import pytest
    from sqlalchemy.exc import IntegrityError

    source = Source(kind="rss", name="AP", feed_url="https://ap.com/rss", category="World")
    session.add(source)
    session.flush()
    for _ in range(2):
        session.add(Post(source_id=source.id, external_id="dup", url="https://ap.com/x",
                         title="t", published_at=datetime.now(timezone.utc)))
    with pytest.raises(IntegrityError):
        session.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.db'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/db.py
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import get_settings


class Base(DeclarativeBase):
    pass


engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

```python
# backend/app/models.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Generate the Alembic migration**

Run `alembic init migrations` inside `backend/`, point `sqlalchemy.url` at the env var in `migrations/env.py`, set `target_metadata = Base.metadata`, then:

```bash
cd backend && alembic revision --autogenerate -m "initial schema"
```

Hand-edit the generated file to add `op.execute("CREATE EXTENSION IF NOT EXISTS vector")` as the first line of `upgrade()`, and add an IVFFlat index on both embedding columns at the end:

```python
op.execute("CREATE INDEX ix_markets_embedding ON markets "
           "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)")
op.execute("CREATE INDEX ix_posts_embedding ON posts "
           "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)")
```

Verify: `alembic upgrade head` then `alembic downgrade base` both succeed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/db.py backend/app/models.py backend/migrations/ backend/alembic.ini backend/tests/
git commit -m "feat: add database schema and initial migration"
```

---

### Task 3: Kalshi API client

**Files:**
- Create: `backend/app/clients/__init__.py`
- Create: `backend/app/clients/kalshi.py`
- Create: `backend/tests/fixtures/kalshi_markets.json`
- Create: `backend/tests/test_kalshi_client.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `app.clients.kalshi.KalshiMarket` — dataclass with `ticker, event_ticker, series_ticker, title, rules_summary, category, status, close_time, yes_price, volume`.
  - `app.clients.kalshi.KalshiClient.fetch_all_markets(status: str = "open") -> list[KalshiMarket]` — follows cursor pagination to exhaustion.
  - `app.clients.kalshi.KalshiClient.fetch_candlesticks(ticker: str, start: datetime, end: datetime) -> list[tuple[datetime, int]]` — `(timestamp, yes_price_cents)` pairs.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_kalshi_client.py
import httpx, respx
from datetime import datetime, timezone
from app.clients.kalshi import KalshiClient, BASE_URL


@respx.mock
def test_fetch_all_markets_follows_pagination():
    page1 = {"markets": [{
        "ticker": "FED-26SEP", "event_ticker": "FED", "title": "Fed cuts in September?",
        "rules_primary": "Resolves YES if lowered.", "category": "Economics",
        "status": "active", "close_time": "2026-09-30T20:00:00Z",
        "yes_bid": 71, "yes_ask": 73, "volume": 5100000,
    }], "cursor": "next123"}
    page2 = {"markets": [{
        "ticker": "GOVSHUT-26OCT", "event_ticker": "GOVSHUT", "title": "Shutdown before Oct 15?",
        "rules_primary": "Resolves YES on a lapse.", "category": "Politics",
        "status": "active", "close_time": "2026-10-15T20:00:00Z",
        "yes_bid": 63, "yes_ask": 65, "volume": 2400000,
    }], "cursor": ""}

    route = respx.get(f"{BASE_URL}/markets")
    route.side_effect = [httpx.Response(200, json=page1), httpx.Response(200, json=page2)]

    markets = KalshiClient().fetch_all_markets()

    assert [m.ticker for m in markets] == ["FED-26SEP", "GOVSHUT-26OCT"]
    assert markets[0].yes_price == 72          # midpoint of bid/ask
    assert markets[0].close_time == datetime(2026, 9, 30, 20, 0, tzinfo=timezone.utc)
    assert route.call_count == 2


@respx.mock
def test_fetch_all_markets_sends_no_auth_headers():
    respx.get(f"{BASE_URL}/markets").mock(
        return_value=httpx.Response(200, json={"markets": [], "cursor": ""}))

    KalshiClient().fetch_all_markets()

    sent = respx.calls[0].request.headers
    assert "KALSHI-ACCESS-KEY" not in sent
    assert "authorization" not in {k.lower() for k in sent}


@respx.mock
def test_fetch_candlesticks_returns_timestamp_price_pairs():
    respx.get(url__regex=rf"{BASE_URL}/series/.*/markets/FED-26SEP/candlesticks").mock(
        return_value=httpx.Response(200, json={"candlesticks": [
            {"end_period_ts": 1789600000, "price": {"close": 68}},
            {"end_period_ts": 1789603600, "price": {"close": 72}},
        ]}))

    points = KalshiClient().fetch_candlesticks(
        "FED-26SEP", datetime(2026, 9, 17, tzinfo=timezone.utc),
        datetime(2026, 9, 18, tzinfo=timezone.utc), series_ticker="FED")

    assert [p[1] for p in points] == [68, 72]
    assert points[0][0].tzinfo is timezone.utc
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_kalshi_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.clients'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/clients/kalshi.py
from dataclasses import dataclass
from datetime import datetime, timezone
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"


@dataclass(frozen=True)
class KalshiMarket:
    ticker: str
    event_ticker: str | None
    series_ticker: str | None
    title: str
    rules_summary: str | None
    category: str | None
    status: str
    close_time: datetime | None
    yes_price: int | None
    volume: int | None


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _midpoint(bid, ask) -> int | None:
    if bid is None and ask is None:
        return None
    if bid is None or ask is None:
        return bid if ask is None else ask
    return round((bid + ask) / 2)


class KalshiClient:
    """Read-only client for Kalshi's public endpoints. Never sends auth headers."""

    def __init__(self, timeout: float = 20.0):
        self._client = httpx.Client(timeout=timeout, headers={"Accept": "application/json"})

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    def _get(self, path: str, params: dict) -> dict:
        response = self._client.get(f"{BASE_URL}{path}", params=params)
        response.raise_for_status()
        return response.json()

    def fetch_all_markets(self, status: str = "open") -> list[KalshiMarket]:
        markets: list[KalshiMarket] = []
        cursor = ""
        while True:
            params = {"limit": 1000, "status": status}
            if cursor:
                params["cursor"] = cursor
            payload = self._get("/markets", params)
            for raw in payload.get("markets", []):
                markets.append(KalshiMarket(
                    ticker=raw["ticker"],
                    event_ticker=raw.get("event_ticker"),
                    series_ticker=raw.get("series_ticker"),
                    title=raw.get("title", ""),
                    rules_summary=raw.get("rules_primary"),
                    category=raw.get("category"),
                    status=raw.get("status", "unknown"),
                    close_time=_parse_ts(raw.get("close_time")),
                    yes_price=_midpoint(raw.get("yes_bid"), raw.get("yes_ask")),
                    volume=raw.get("volume"),
                ))
            cursor = payload.get("cursor") or ""
            if not cursor:
                return markets

    def fetch_candlesticks(self, ticker: str, start: datetime, end: datetime,
                           series_ticker: str | None = None,
                           period_interval: int = 60) -> list[tuple[datetime, int]]:
        series = series_ticker or ticker.split("-")[0]
        payload = self._get(
            f"/series/{series}/markets/{ticker}/candlesticks",
            {"start_ts": int(start.timestamp()), "end_ts": int(end.timestamp()),
             "period_interval": period_interval},
        )
        points = []
        for candle in payload.get("candlesticks", []):
            close = (candle.get("price") or {}).get("close")
            if close is None:
                continue
            points.append((datetime.fromtimestamp(candle["end_period_ts"], tz=timezone.utc), close))
        return points
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_kalshi_client.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/clients/ backend/tests/test_kalshi_client.py
git commit -m "feat: add read-only Kalshi API client"
```

---

### Task 4: Embedding client and market text composition

**Files:**
- Create: `backend/app/embeddings.py`
- Create: `backend/app/market_text.py`
- Create: `backend/tests/test_market_text.py`
- Create: `backend/tests/test_embeddings.py`

**Interfaces:**
- Consumes: `app.clients.kalshi.KalshiMarket`.
- Produces:
  - `app.market_text.compose_market_text(market: KalshiMarket) -> str`
  - `app.market_text.text_hash(text: str) -> str` — sha256 hex digest, 64 chars.
  - `app.embeddings.embed_texts(texts: list[str]) -> list[list[float]]` — batched, 1536-dim vectors, preserves input order.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_market_text.py
from datetime import datetime, timezone
from app.clients.kalshi import KalshiMarket
from app.market_text import compose_market_text, text_hash

MARKET = KalshiMarket(
    ticker="FED-26SEP-T4.50", event_ticker="FED", series_ticker="FED",
    title="Fed target rate above 4.50% in September?",
    rules_summary="Resolves YES if the upper bound exceeds 4.50%.",
    category="Economics", status="active",
    close_time=datetime(2026, 9, 30, tzinfo=timezone.utc), yes_price=72, volume=1,
)


def test_composed_text_is_human_readable_not_just_the_ticker():
    text = compose_market_text(MARKET)
    assert "Fed target rate above 4.50% in September?" in text
    assert "Resolves YES if the upper bound exceeds 4.50%." in text
    assert "Economics" in text
    assert "2026-09-30" in text
    assert "FED-26SEP-T4.50" not in text


def test_text_hash_is_stable_and_changes_with_content():
    assert text_hash("abc") == text_hash("abc")
    assert len(text_hash("abc")) == 64
    assert text_hash("abc") != text_hash("abd")
```

```python
# backend/tests/test_embeddings.py
from unittest.mock import MagicMock, patch
from app.embeddings import embed_texts, EMBED_MODEL


def test_embed_texts_preserves_order_and_uses_the_right_model():
    fake = MagicMock()
    fake.data = [MagicMock(embedding=[0.1] * 1536, index=0),
                 MagicMock(embedding=[0.2] * 1536, index=1)]
    with patch("app.embeddings._client") as client:
        client.embeddings.create.return_value = fake
        vectors = embed_texts(["first", "second"])

    assert len(vectors) == 2
    assert vectors[0][0] == 0.1 and vectors[1][0] == 0.2
    assert client.embeddings.create.call_args.kwargs["model"] == EMBED_MODEL


def test_embed_texts_returns_empty_for_empty_input():
    assert embed_texts([]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_market_text.py tests/test_embeddings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.market_text'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/market_text.py
import hashlib
from app.clients.kalshi import KalshiMarket


def compose_market_text(market: KalshiMarket) -> str:
    """Build the string a market is embedded as.

    Tickers like FED-26SEP-T4.50 carry no semantic signal, so they are
    deliberately excluded — only human-readable fields are embedded.
    """
    parts = [market.title]
    if market.rules_summary:
        parts.append(market.rules_summary)
    if market.category:
        parts.append(f"Category: {market.category}")
    if market.close_time:
        parts.append(f"Closes {market.close_time.date().isoformat()}")
    return " — ".join(parts)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
```

```python
# backend/app/embeddings.py
from openai import OpenAI
from app.config import get_settings

EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
BATCH_SIZE = 256

_client = OpenAI(api_key=get_settings().openai_api_key or "unset")


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]
        response = _client.embeddings.create(model=EMBED_MODEL, input=batch)
        vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
    return vectors
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_market_text.py tests/test_embeddings.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/market_text.py backend/app/embeddings.py backend/tests/test_market_text.py backend/tests/test_embeddings.py
git commit -m "feat: add market text composition and embedding client"
```

---

### Task 5: Kalshi sync job

**Files:**
- Create: `backend/app/jobs/__init__.py`
- Create: `backend/app/jobs/sync_markets.py`
- Create: `backend/tests/test_sync_markets.py`

**Interfaces:**
- Consumes: `KalshiClient.fetch_all_markets`, `compose_market_text`, `text_hash`, `embed_texts`, `app.models.Market`.
- Produces: `app.jobs.sync_markets.sync_markets(session, client=None) -> int` — returns the number of markets upserted. Only embeds markets whose `text_hash` changed.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_sync_markets.py
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from app.clients.kalshi import KalshiMarket
from app.jobs.sync_markets import sync_markets
from app.models import Market

M = KalshiMarket(
    ticker="FED-26SEP", event_ticker="FED", series_ticker="FED",
    title="Fed cuts in September?", rules_summary="Resolves YES if lowered.",
    category="Economics", status="active",
    close_time=datetime(2026, 9, 30, tzinfo=timezone.utc), yes_price=72, volume=5100000,
)


def _client(markets):
    client = MagicMock()
    client.fetch_all_markets.return_value = markets
    return client


def test_sync_inserts_markets_and_embeds_them(session):
    with patch("app.jobs.sync_markets.embed_texts", return_value=[[0.3] * 1536]) as embed:
        count = sync_markets(session, client=_client([M]))

    assert count == 1
    market = session.query(Market).one()
    assert market.ticker == "FED-26SEP"
    assert market.yes_price == 72
    assert market.embedding is not None
    assert embed.call_count == 1


def test_resync_with_unchanged_text_does_not_re_embed(session):
    with patch("app.jobs.sync_markets.embed_texts", return_value=[[0.3] * 1536]):
        sync_markets(session, client=_client([M]))

    updated = KalshiMarket(**{**M.__dict__, "yes_price": 80})
    with patch("app.jobs.sync_markets.embed_texts", return_value=[]) as embed:
        sync_markets(session, client=_client([updated]))

    assert embed.call_args.args[0] == []          # nothing re-embedded
    assert session.query(Market).one().yes_price == 80   # price still refreshed


def test_sync_is_idempotent(session):
    with patch("app.jobs.sync_markets.embed_texts", return_value=[[0.3] * 1536]):
        sync_markets(session, client=_client([M]))
        sync_markets(session, client=_client([M]))

    assert session.query(Market).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_sync_markets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.jobs'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/jobs/sync_markets.py
from datetime import datetime, timezone
from app.clients.kalshi import KalshiClient
from app.embeddings import embed_texts
from app.market_text import compose_market_text, text_hash
from app.models import Market


def sync_markets(session, client: KalshiClient | None = None) -> int:
    client = client or KalshiClient()
    fetched = client.fetch_all_markets()

    existing = {m.ticker: m for m in session.query(Market).all()}
    needs_embedding: list[tuple[Market, str]] = []

    for incoming in fetched:
        composed = compose_market_text(incoming)
        digest = text_hash(composed)
        market = existing.get(incoming.ticker)

        if market is None:
            market = Market(ticker=incoming.ticker)
            session.add(market)

        market.event_ticker = incoming.event_ticker
        market.series_ticker = incoming.series_ticker
        market.title = incoming.title
        market.rules_summary = incoming.rules_summary
        market.category = incoming.category
        market.status = incoming.status
        market.close_time = incoming.close_time
        market.yes_price = incoming.yes_price
        market.volume = incoming.volume
        market.updated_at = datetime.now(timezone.utc)

        if market.text_hash != digest:
            market.text_hash = digest
            needs_embedding.append((market, composed))

    vectors = embed_texts([text for _, text in needs_embedding])
    for (market, _), vector in zip(needs_embedding, vectors):
        market.embedding = vector

    session.commit()
    return len(fetched)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_sync_markets.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/jobs/ backend/tests/test_sync_markets.py
git commit -m "feat: add Kalshi market sync job with hash-gated re-embedding"
```

---

### Task 6: Ingestor protocol and RSS ingestor

**Files:**
- Create: `backend/app/ingest/__init__.py`
- Create: `backend/app/ingest/base.py`
- Create: `backend/app/ingest/rss.py`
- Create: `backend/tests/fixtures/reuters.xml`
- Create: `backend/tests/test_rss_ingestor.py`

**Interfaces:**
- Consumes: `app.models.Source`.
- Produces:
  - `app.ingest.base.RawPost` — dataclass `external_id, url, title, body, author_name, author_handle, avatar_url, published_at`.
  - `app.ingest.base.Ingestor` — Protocol with `kind: str` and `fetch(source, since) -> list[RawPost]`.
  - `app.ingest.rss.RssIngestor` implementing it.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/fixtures/reuters.xml` with a two-item RSS 2.0 feed (items titled "Powell signals openness to a September cut" and "Shutdown talks collapse", with `<pubDate>` values of `Wed, 17 Sep 2026 14:02:00 GMT` and `Wed, 17 Sep 2026 13:10:00 GMT`, `<link>` and `<description>` elements, and a `<guid>` on the first item only).

```python
# backend/tests/test_rss_ingestor.py
from datetime import datetime, timezone
from pathlib import Path
import httpx, respx
from app.ingest.rss import RssIngestor
from app.models import Source

FEED = (Path(__file__).parent / "fixtures" / "reuters.xml").read_text()
SOURCE = Source(id=1, kind="rss", name="Reuters",
                feed_url="https://example.com/rss", category="Economics")


@respx.mock
def test_fetch_parses_items_into_raw_posts():
    respx.get(SOURCE.feed_url).mock(return_value=httpx.Response(200, text=FEED))

    posts = RssIngestor().fetch(SOURCE, since=datetime(2026, 9, 1, tzinfo=timezone.utc))

    assert len(posts) == 2
    assert posts[0].title == "Powell signals openness to a September cut"
    assert posts[0].author_name == "Reuters"
    assert posts[0].published_at == datetime(2026, 9, 17, 14, 2, tzinfo=timezone.utc)
    assert posts[0].url.startswith("http")


@respx.mock
def test_fetch_skips_items_older_than_since():
    respx.get(SOURCE.feed_url).mock(return_value=httpx.Response(200, text=FEED))

    posts = RssIngestor().fetch(SOURCE, since=datetime(2026, 9, 17, 13, 30, tzinfo=timezone.utc))

    assert [p.title for p in posts] == ["Powell signals openness to a September cut"]


@respx.mock
def test_external_id_falls_back_to_url_when_guid_missing():
    respx.get(SOURCE.feed_url).mock(return_value=httpx.Response(200, text=FEED))

    posts = RssIngestor().fetch(SOURCE, since=datetime(2026, 9, 1, tzinfo=timezone.utc))

    assert posts[1].external_id == posts[1].url


@respx.mock
def test_http_error_raises_so_the_caller_can_isolate_the_source():
    import pytest
    respx.get(SOURCE.feed_url).mock(return_value=httpx.Response(503))

    with pytest.raises(httpx.HTTPStatusError):
        RssIngestor().fetch(SOURCE, since=datetime(2026, 9, 1, tzinfo=timezone.utc))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_rss_ingestor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingest'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/ingest/base.py
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class RawPost:
    external_id: str
    url: str
    title: str
    body: str | None = None
    author_name: str | None = None
    author_handle: str | None = None
    avatar_url: str | None = None
    published_at: datetime | None = None


class Ingestor(Protocol):
    kind: str

    def fetch(self, source, since: datetime) -> list[RawPost]: ...
```

```python
# backend/app/ingest/rss.py
from calendar import timegm
from datetime import datetime, timezone
import feedparser, httpx
from app.ingest.base import RawPost


class RssIngestor:
    kind = "rss"

    def __init__(self, timeout: float = 20.0):
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch(self, source, since: datetime) -> list[RawPost]:
        response = self._client.get(source.feed_url)
        response.raise_for_status()
        feed = feedparser.parse(response.text)

        posts: list[RawPost] = []
        for entry in feed.entries:
            published = self._published(entry)
            if published is None or published <= since:
                continue
            url = entry.get("link", "")
            posts.append(RawPost(
                external_id=entry.get("id") or url,
                url=url,
                title=entry.get("title", "").strip(),
                body=(entry.get("summary") or "").strip() or None,
                author_name=source.name,
                published_at=published,
            ))
        return posts

    @staticmethod
    def _published(entry) -> datetime | None:
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed is None:
            return None
        return datetime.fromtimestamp(timegm(parsed), tz=timezone.utc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_rss_ingestor.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingest/ backend/tests/test_rss_ingestor.py backend/tests/fixtures/reuters.xml
git commit -m "feat: add ingestor protocol and RSS ingestor"
```

---

### Task 7: X ingestor via discovery and oEmbed hydration

**Files:**
- Create: `backend/app/ingest/x.py`
- Create: `backend/tests/test_x_ingestor.py`

**Interfaces:**
- Consumes: `app.ingest.base.RawPost`.
- Produces:
  - `app.ingest.x.extract_tweet_ids(html: str) -> list[str]` — unique, order-preserving tweet IDs found in article HTML.
  - `app.ingest.x.XIngestor.hydrate(tweet_id: str) -> RawPost | None` — one oEmbed call; returns `None` on 404/403 (deleted or protected).
  - `app.ingest.x.XIngestor.fetch(source, since) -> list[RawPost]`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_x_ingestor.py
import httpx, respx
from app.ingest.x import extract_tweet_ids, XIngestor, OEMBED_URL

ARTICLE = """
<p>As <a href="https://twitter.com/NickTimiraos/status/1839000000000000001">one reporter noted</a>…</p>
<blockquote class="twitter-tweet"><a href="https://x.com/federalreserve/status/1839000000000000002?s=20"></a></blockquote>
<p>Duplicate: <a href="https://x.com/NickTimiraos/status/1839000000000000001">same</a></p>
<p>Not a tweet: <a href="https://x.com/NickTimiraos">profile</a></p>
"""

OEMBED_PAYLOAD = {
    "author_name": "Nick Timiraos",
    "author_url": "https://twitter.com/NickTimiraos",
    "html": '<blockquote><p>The internal debate has shifted from whether to cut '
            'to <b>how much</b>.</p>&mdash; Nick Timiraos</blockquote>',
    "url": "https://twitter.com/NickTimiraos/status/1839000000000000001",
}


def test_extract_tweet_ids_dedupes_and_ignores_non_status_links():
    assert extract_tweet_ids(ARTICLE) == ["1839000000000000001", "1839000000000000002"]


def test_extract_tweet_ids_handles_html_with_no_tweets():
    assert extract_tweet_ids("<p>nothing here</p>") == []


@respx.mock
def test_hydrate_builds_a_raw_post_with_author_and_clean_text():
    respx.get(OEMBED_URL).mock(return_value=httpx.Response(200, json=OEMBED_PAYLOAD))

    post = XIngestor().hydrate("1839000000000000001")

    assert post.external_id == "1839000000000000001"
    assert post.author_name == "Nick Timiraos"
    assert post.author_handle == "@NickTimiraos"
    assert "how much" in post.title
    assert "<b>" not in post.title          # HTML stripped
    assert post.url == "https://twitter.com/NickTimiraos/status/1839000000000000001"


@respx.mock
def test_hydrate_returns_none_for_deleted_or_protected_tweets():
    respx.get(OEMBED_URL).mock(return_value=httpx.Response(404))

    assert XIngestor().hydrate("1839000000000000009") is None


@respx.mock
def test_hydrate_never_sends_credentials():
    respx.get(OEMBED_URL).mock(return_value=httpx.Response(200, json=OEMBED_PAYLOAD))

    XIngestor().hydrate("1839000000000000001")

    headers = {k.lower() for k in respx.calls[0].request.headers}
    assert "authorization" not in headers
    assert "cookie" not in headers
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_x_ingestor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingest.x'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/ingest/x.py
import html as html_lib
import re
from datetime import datetime
import httpx
from app.ingest.base import RawPost

OEMBED_URL = "https://publish.twitter.com/oembed"

_STATUS_RE = re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/[^/\s\"']+/status/(\d+)")
_TAG_RE = re.compile(r"<[^>]+>")
_TRAILING_ATTRIB_RE = re.compile(r"&mdash;.*$", re.DOTALL)


def extract_tweet_ids(html: str) -> list[str]:
    seen: dict[str, None] = {}
    for match in _STATUS_RE.finditer(html or ""):
        seen.setdefault(match.group(1), None)
    return list(seen)


def _tweet_text(embed_html: str) -> str:
    text = _TRAILING_ATTRIB_RE.sub("", embed_html or "")
    text = _TAG_RE.sub(" ", text)
    return " ".join(html_lib.unescape(text).split())


class XIngestor:
    """Discovers tweet IDs from article HTML, then hydrates each one exactly once
    through X's public oEmbed endpoint. No scraping, no credentials, no browser."""

    kind = "x"

    def __init__(self, timeout: float = 15.0):
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)

    def hydrate(self, tweet_id: str) -> RawPost | None:
        response = self._client.get(OEMBED_URL, params={
            "url": f"https://twitter.com/i/status/{tweet_id}",
            "omit_script": "true", "dnt": "true",
        })
        if response.status_code in (401, 403, 404):
            return None
        response.raise_for_status()
        payload = response.json()

        author_url = payload.get("author_url") or ""
        handle = author_url.rstrip("/").rsplit("/", 1)[-1]
        return RawPost(
            external_id=tweet_id,
            url=payload.get("url") or author_url,
            title=_tweet_text(payload.get("html", "")),
            body=None,
            author_name=payload.get("author_name"),
            author_handle=f"@{handle}" if handle else None,
            published_at=None,
        )

    def fetch(self, source, since: datetime) -> list[RawPost]:
        """Hydrate any pending tweet IDs queued for this source.

        Discovery happens in the ingest job, which scans fetched article HTML
        with extract_tweet_ids and queues what it finds on the source.
        """
        pending = getattr(source, "pending_tweet_ids", None) or []
        posts = []
        for tweet_id in pending:
            post = self.hydrate(tweet_id)
            if post is not None:
                posts.append(post)
        return posts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_x_ingestor.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingest/x.py backend/tests/test_x_ingestor.py
git commit -m "feat: add X ingestor using discovery and oEmbed hydration"
```

---

### Task 8: Ingest job with per-source isolation and permanent caching

**Files:**
- Create: `backend/app/jobs/ingest.py`
- Create: `backend/tests/test_ingest_job.py`

**Interfaces:**
- Consumes: `RssIngestor`, `XIngestor`, `extract_tweet_ids`, `app.models.Post`, `Source`, `JobRun`.
- Produces: `app.jobs.ingest.run_ingest(session, ingestors: dict[str, Ingestor] | None = None) -> int` — returns the count of newly stored posts. Records a `JobRun` row. A failing source is logged and skipped, never raised.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ingest_job.py
from datetime import datetime, timezone
from unittest.mock import MagicMock
import httpx
from app.ingest.base import RawPost
from app.jobs.ingest import run_ingest
from app.models import JobRun, Post, Source

POST = RawPost(external_id="guid-1", url="https://r.com/a", title="Powell signals cut",
               body="Officials see room to ease.", author_name="Reuters",
               published_at=datetime(2026, 9, 17, 14, 2, tzinfo=timezone.utc))


def _ingestor(posts, kind="rss"):
    ingestor = MagicMock()
    ingestor.kind = kind
    ingestor.fetch.return_value = posts
    return ingestor


def test_ingest_stores_new_posts(session):
    session.add(Source(kind="rss", name="Reuters", feed_url="https://r.com/rss",
                       category="Economics"))
    session.commit()

    count = run_ingest(session, ingestors={"rss": _ingestor([POST])})

    assert count == 1
    post = session.query(Post).one()
    assert post.title == "Powell signals cut"
    assert post.category == "Economics"


def test_reingesting_the_same_item_is_a_no_op(session):
    session.add(Source(kind="rss", name="Reuters", feed_url="https://r.com/rss",
                       category="Economics"))
    session.commit()

    run_ingest(session, ingestors={"rss": _ingestor([POST])})
    second = run_ingest(session, ingestors={"rss": _ingestor([POST])})

    assert second == 0
    assert session.query(Post).count() == 1


def test_one_failing_source_does_not_stop_the_others(session):
    session.add_all([
        Source(kind="rss", name="Broken", feed_url="https://broken.com/rss", category="World"),
        Source(kind="rss", name="Reuters", feed_url="https://r.com/rss", category="Economics"),
    ])
    session.commit()

    ingestor = MagicMock()
    ingestor.kind = "rss"
    ingestor.fetch.side_effect = [httpx.ConnectError("boom"), [POST]]

    count = run_ingest(session, ingestors={"rss": ingestor})

    assert count == 1
    assert session.query(Post).count() == 1


def test_disabled_sources_are_skipped(session):
    session.add(Source(kind="rss", name="Off", feed_url="https://off.com/rss",
                       category="World", enabled=False))
    session.commit()

    ingestor = _ingestor([POST])
    assert run_ingest(session, ingestors={"rss": ingestor}) == 0
    ingestor.fetch.assert_not_called()


def test_job_run_is_recorded(session):
    session.add(Source(kind="rss", name="Reuters", feed_url="https://r.com/rss",
                       category="Economics"))
    session.commit()

    run_ingest(session, ingestors={"rss": _ingestor([POST])})

    run = session.query(JobRun).filter_by(job="ingest").one()
    assert run.status == "ok"
    assert run.items_processed == 1
    assert run.finished_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_ingest_job.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.jobs.ingest'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/jobs/ingest.py
import logging
from datetime import datetime, timedelta, timezone
from app.ingest.rss import RssIngestor
from app.ingest.x import XIngestor
from app.models import JobRun, Post, Source

logger = logging.getLogger(__name__)
LOOKBACK = timedelta(hours=6)


def _default_ingestors():
    return {"rss": RssIngestor(), "x": XIngestor()}


def run_ingest(session, ingestors: dict | None = None) -> int:
    ingestors = ingestors or _default_ingestors()
    run = JobRun(job="ingest", status="running")
    session.add(run)
    session.commit()

    since = datetime.now(timezone.utc) - LOOKBACK
    stored = 0

    for source in session.query(Source).filter_by(enabled=True).all():
        ingestor = ingestors.get(source.kind)
        if ingestor is None:
            continue
        try:
            raw_posts = ingestor.fetch(source, since)
        except Exception as exc:                       # isolate per source
            logger.warning("source %s failed: %s", source.name, exc)
            continue

        for raw in raw_posts:
            exists = session.query(Post.id).filter_by(
                source_id=source.id, external_id=raw.external_id).first()
            if exists:
                continue
            session.add(Post(
                source_id=source.id,
                external_id=raw.external_id,
                url=raw.url,
                title=raw.title,
                body=raw.body,
                author_name=raw.author_name,
                author_handle=raw.author_handle,
                avatar_url=raw.avatar_url,
                category=source.category,
                published_at=raw.published_at or datetime.now(timezone.utc),
            ))
            stored += 1
        session.commit()

    run.status = "ok"
    run.items_processed = stored
    run.finished_at = datetime.now(timezone.utc)
    session.commit()
    return stored
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_ingest_job.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/jobs/ingest.py backend/tests/test_ingest_job.py
git commit -m "feat: add ingest job with per-source isolation"
```

---

### Task 9: Candidate retrieval from pgvector

**Files:**
- Create: `backend/app/linker/__init__.py`
- Create: `backend/app/linker/retrieval.py`
- Create: `backend/tests/test_retrieval.py`

**Interfaces:**
- Consumes: `app.models.Market`, `Post`.
- Produces: `app.linker.retrieval.find_candidates(session, post, limit=10, max_distance=0.55) -> list[Candidate]` where `Candidate` is a dataclass of `ticker, title, rules_summary, close_time, yes_price, volume, distance`. Filters to `status == "open"` and `close_time > now`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_retrieval.py
from datetime import datetime, timedelta, timezone
from app.linker.retrieval import find_candidates
from app.models import Market, Post, Source

NOW = datetime.now(timezone.utc)


def _vec(value: float):
    return [value] + [0.0] * 1535


def _market(session, ticker, value, status="open", close_in_days=30):
    session.add(Market(
        ticker=ticker, title=f"{ticker} question?", rules_summary="Resolves YES.",
        category="Economics", status=status, close_time=NOW + timedelta(days=close_in_days),
        yes_price=50, volume=1000, text_hash=ticker, embedding=_vec(value)))


def _post(session, value: float) -> Post:
    source = Source(kind="rss", name="R", feed_url="u", category="Economics")
    session.add(source)
    session.flush()
    post = Post(source_id=source.id, external_id=f"e{value}", url="u", title="t",
                published_at=NOW, embedding=_vec(value))
    session.add(post)
    session.commit()
    return post


def test_returns_nearest_markets_ordered_by_distance(session):
    _market(session, "NEAR", 1.0)
    _market(session, "FAR", -1.0)
    post = _post(session, 1.0)

    candidates = find_candidates(session, post, limit=10, max_distance=2.0)

    assert [c.ticker for c in candidates] == ["NEAR", "FAR"]
    assert candidates[0].distance < candidates[1].distance


def test_excludes_settled_and_expired_markets(session):
    _market(session, "SETTLED", 1.0, status="settled")
    _market(session, "EXPIRED", 1.0, close_in_days=-1)
    _market(session, "GOOD", 1.0)
    post = _post(session, 1.0)

    assert [c.ticker for c in find_candidates(session, post, max_distance=2.0)] == ["GOOD"]


def test_distance_floor_filters_out_weak_matches(session):
    _market(session, "FAR", -1.0)
    post = _post(session, 1.0)

    assert find_candidates(session, post, max_distance=0.5) == []


def test_post_without_embedding_returns_nothing(session):
    _market(session, "ANY", 1.0)
    source = Source(kind="rss", name="R", feed_url="u", category="Economics")
    session.add(source)
    session.flush()
    post = Post(source_id=source.id, external_id="none", url="u", title="t", published_at=NOW)
    session.add(post)
    session.commit()

    assert find_candidates(session, post) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_retrieval.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.linker'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/linker/retrieval.py
from dataclasses import dataclass
from datetime import datetime, timezone
from app.models import Market, Post


@dataclass(frozen=True)
class Candidate:
    ticker: str
    title: str
    rules_summary: str | None
    close_time: datetime | None
    yes_price: int | None
    volume: int | None
    distance: float


def find_candidates(session, post: Post, limit: int = 10,
                    max_distance: float = 0.55) -> list[Candidate]:
    if post.embedding is None:
        return []

    distance = Market.embedding.cosine_distance(post.embedding).label("distance")
    rows = (
        session.query(Market, distance)
        .filter(Market.embedding.isnot(None))
        .filter(Market.status == "open")
        .filter(Market.close_time > datetime.now(timezone.utc))
        .filter(distance <= max_distance)
        .order_by(distance)
        .limit(limit)
        .all()
    )
    return [
        Candidate(
            ticker=market.ticker, title=market.title, rules_summary=market.rules_summary,
            close_time=market.close_time, yes_price=market.yes_price,
            volume=market.volume, distance=float(dist),
        )
        for market, dist in rows
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_retrieval.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/linker/ backend/tests/test_retrieval.py
git commit -m "feat: add pgvector candidate retrieval with open-market filters"
```

---

### Task 10: LLM verifier with spend cap

**Files:**
- Create: `backend/app/linker/verifier.py`
- Create: `backend/app/spend.py`
- Create: `backend/tests/test_spend.py`
- Create: `backend/tests/test_verifier.py`

**Interfaces:**
- Consumes: `app.linker.retrieval.Candidate`, `app.models.LlmSpend`.
- Produces:
  - `app.spend.record_spend(session, usd: float) -> None` and `app.spend.budget_remaining(session) -> float`.
  - `app.linker.verifier.VerifiedLink` — pydantic model `ticker, related, direction, confidence, rationale`.
  - `app.linker.verifier.verify_candidates(post, candidates, client=None) -> list[VerifiedLink]` — one Haiku call, retried once on malformed output, returns `[]` on persistent failure.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_spend.py
from app.spend import budget_remaining, record_spend


def test_budget_starts_at_the_configured_daily_limit(session):
    assert budget_remaining(session) == 1.0


def test_spend_accumulates_within_the_same_day(session):
    record_spend(session, 0.25)
    record_spend(session, 0.10)
    assert round(budget_remaining(session), 4) == 0.65


def test_budget_never_reports_negative(session):
    record_spend(session, 5.0)
    assert budget_remaining(session) == 0.0
```

```python
# backend/tests/test_verifier.py
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from app.linker.retrieval import Candidate
from app.linker.verifier import verify_candidates

NOW = datetime.now(timezone.utc)
POST = MagicMock(title="Shutdown talks collapse", body="Leadership walked out.",
                 author_name="Politico", published_at=NOW)
CANDIDATES = [
    Candidate("GOVSHUT-26OCT", "Shutdown before Oct 15?", "Resolves YES on a lapse.",
              NOW + timedelta(days=28), 64, 2400000, 0.11),
    Candidate("NFL-WEEK3", "Chiefs win week 3?", "Resolves YES if they win.",
              NOW + timedelta(days=4), 55, 90000, 0.49),
]


def _client(payload: str):
    client = MagicMock()
    client.messages.create.return_value = MagicMock(
        content=[MagicMock(text=payload)],
        usage=MagicMock(input_tokens=1200, output_tokens=300))
    return client


def test_returns_only_related_links():
    payload = json.dumps({"links": [
        {"ticker": "GOVSHUT-26OCT", "related": True, "direction": "YES",
         "confidence": 0.86, "rationale": "Walking out removes the last path to a deal."},
        {"ticker": "NFL-WEEK3", "related": False, "direction": "YES",
         "confidence": 0.02, "rationale": "Unrelated."},
    ]})

    links = verify_candidates(POST, CANDIDATES, client=_client(payload))

    assert [link.ticker for link in links] == ["GOVSHUT-26OCT"]
    assert links[0].direction == "YES"
    assert links[0].confidence == 0.86


def test_hallucinated_tickers_are_discarded():
    payload = json.dumps({"links": [
        {"ticker": "NOT-A-REAL-TICKER", "related": True, "direction": "YES",
         "confidence": 0.99, "rationale": "Invented."}]})

    assert verify_candidates(POST, CANDIDATES, client=_client(payload)) == []


def test_malformed_output_retries_once_then_returns_empty():
    client = _client("this is not json")

    links = verify_candidates(POST, CANDIDATES, client=client)

    assert links == []
    assert client.messages.create.call_count == 2


def test_no_candidates_means_no_llm_call():
    client = _client("{}")
    assert verify_candidates(POST, [], client=client) == []
    client.messages.create.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_spend.py tests/test_verifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.spend'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/spend.py
from datetime import date
from app.config import get_settings
from app.models import LlmSpend


def record_spend(session, usd: float) -> None:
    today = date.today()
    row = session.get(LlmSpend, today)
    if row is None:
        row = LlmSpend(day=today, usd=0)
        session.add(row)
    row.usd = float(row.usd) + usd
    session.commit()


def budget_remaining(session) -> float:
    row = session.get(LlmSpend, date.today())
    spent = float(row.usd) if row else 0.0
    return max(0.0, get_settings().daily_llm_budget_usd - spent)
```

```python
# backend/app/linker/verifier.py
import json
import logging
from anthropic import Anthropic
from pydantic import BaseModel, Field, ValidationError
from app.config import get_settings
from app.linker.retrieval import Candidate

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
INPUT_USD_PER_TOKEN = 1.0 / 1_000_000
OUTPUT_USD_PER_TOKEN = 5.0 / 1_000_000

SYSTEM = """You match news items to prediction markets on Kalshi.

For each candidate market, decide whether the news item is genuinely
relevant to how that market resolves. Be strict: a shared topic is not
enough. Reject a market whose close date falls outside the timeframe the
news is about.

When related, state the direction the news pushes the market — YES if it
makes the market more likely to resolve YES, NO otherwise — and give a
single-sentence rationale in plain English, quoting the specific fact
that drives it.

Reply with JSON only, no prose:
{"links": [{"ticker": "...", "related": true, "direction": "YES",
            "confidence": 0.0, "rationale": "..."}]}
Include one entry per candidate."""


class VerifiedLink(BaseModel):
    ticker: str
    related: bool
    direction: str = Field(pattern="^(YES|NO)$")
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


class _Response(BaseModel):
    links: list[VerifiedLink]


def _prompt(post, candidates: list[Candidate]) -> str:
    lines = [f"NEWS ITEM\nSource: {post.author_name}\nHeadline: {post.title}"]
    if post.body:
        lines.append(f"Excerpt: {post.body[:800]}")
    lines.append("\nCANDIDATE MARKETS")
    for candidate in candidates:
        close = candidate.close_time.date().isoformat() if candidate.close_time else "unknown"
        lines.append(
            f"- ticker: {candidate.ticker}\n  question: {candidate.title}\n"
            f"  rules: {candidate.rules_summary or 'n/a'}\n  closes: {close}")
    return "\n".join(lines)


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return input_tokens * INPUT_USD_PER_TOKEN + output_tokens * OUTPUT_USD_PER_TOKEN


def verify_candidates(post, candidates: list[Candidate], client=None) -> list[VerifiedLink]:
    if not candidates:
        return []
    client = client or Anthropic(api_key=get_settings().anthropic_api_key)
    valid_tickers = {candidate.ticker for candidate in candidates}
    prompt = _prompt(post, candidates)

    for attempt in range(2):
        message = client.messages.create(
            model=MODEL, max_tokens=1024, system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].removeprefix("json").strip()
        try:
            parsed = _Response(**json.loads(raw))
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            logger.warning("verifier returned unusable output (attempt %s): %s", attempt + 1, exc)
            continue
        return [
            link for link in parsed.links
            if link.related and link.ticker in valid_tickers
        ]
    return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_spend.py tests/test_verifier.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/spend.py backend/app/linker/verifier.py backend/tests/test_spend.py backend/tests/test_verifier.py
git commit -m "feat: add LLM link verifier and daily spend cap"
```

---

### Task 11: Linker job wiring retrieval, verification, and clustering

**Files:**
- Create: `backend/app/linker/clustering.py`
- Create: `backend/app/jobs/link.py`
- Create: `backend/tests/test_clustering.py`
- Create: `backend/tests/test_link_job.py`

**Interfaces:**
- Consumes: `find_candidates`, `verify_candidates`, `embed_texts`, `budget_remaining`, `record_spend`, `Post`, `PostMarket`, `Cluster`, `Market`.
- Produces:
  - `app.linker.clustering.assign_cluster(session, post, window_hours=24, threshold=0.15) -> int` — returns the cluster id.
  - `app.jobs.link.run_link(session, limit=100) -> int` — embeds unembedded posts, clusters them, links cluster representatives, returns the number of links written. Pauses when `budget_remaining` is zero.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_clustering.py
from datetime import datetime, timedelta, timezone
from app.linker.clustering import assign_cluster
from app.models import Cluster, Post, Source

NOW = datetime.now(timezone.utc)


def _post(session, external_id, vec, published_at=None):
    source = session.query(Source).first()
    if source is None:
        source = Source(kind="rss", name="R", feed_url="u", category="Economics")
        session.add(source)
        session.flush()
    post = Post(source_id=source.id, external_id=external_id, url="u", title=external_id,
                published_at=published_at or NOW, embedding=vec)
    session.add(post)
    session.commit()
    return post


def test_near_identical_posts_share_a_cluster(session):
    first = _post(session, "a", [1.0] + [0.0] * 1535)
    second = _post(session, "b", [0.99, 0.01] + [0.0] * 1534)

    assert assign_cluster(session, first) == assign_cluster(session, second)
    assert session.query(Cluster).count() == 1


def test_unrelated_posts_get_separate_clusters(session):
    first = _post(session, "a", [1.0] + [0.0] * 1535)
    second = _post(session, "b", [-1.0] + [0.0] * 1535)

    assert assign_cluster(session, first) != assign_cluster(session, second)
    assert session.query(Cluster).count() == 2


def test_posts_outside_the_window_do_not_cluster(session):
    old = _post(session, "a", [1.0] + [0.0] * 1535, published_at=NOW - timedelta(days=3))
    new = _post(session, "b", [1.0] + [0.0] * 1535)

    assert assign_cluster(session, old) != assign_cluster(session, new)
```

```python
# backend/tests/test_link_job.py
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from app.jobs.link import run_link
from app.linker.verifier import VerifiedLink
from app.models import Market, Post, PostMarket, Source

NOW = datetime.now(timezone.utc)


def _setup(session):
    source = Source(kind="rss", name="Politico", feed_url="u", category="Politics")
    session.add(source)
    session.flush()
    session.add(Market(
        ticker="GOVSHUT-26OCT", title="Shutdown before Oct 15?",
        rules_summary="Resolves YES on a lapse.", category="Politics", status="open",
        close_time=NOW + timedelta(days=28), yes_price=64, volume=2400000,
        text_hash="h", embedding=[1.0] + [0.0] * 1535))
    session.add(Post(source_id=source.id, external_id="p1", url="u",
                     title="Shutdown talks collapse", published_at=NOW))
    session.commit()


LINK = VerifiedLink(ticker="GOVSHUT-26OCT", related=True, direction="YES",
                    confidence=0.86, rationale="Talks collapsed with no path to a deal.")


def test_link_writes_post_markets_with_price_snapshot(session):
    _setup(session)
    with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535]), \
         patch("app.jobs.link.verify_candidates", return_value=[LINK]):
        written = run_link(session)

    assert written == 1
    link = session.query(PostMarket).one()
    assert link.ticker == "GOVSHUT-26OCT"
    assert link.direction == "YES"
    assert link.price_at_link == 64
    assert link.rationale.startswith("Talks collapsed")


def test_already_linked_posts_are_not_reprocessed(session):
    _setup(session)
    with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535]), \
         patch("app.jobs.link.verify_candidates", return_value=[LINK]) as verify:
        run_link(session)
        run_link(session)

    assert verify.call_count == 1
    assert session.query(PostMarket).count() == 1


def test_low_confidence_links_are_dropped(session):
    _setup(session)
    weak = VerifiedLink(ticker="GOVSHUT-26OCT", related=True, direction="YES",
                        confidence=0.20, rationale="Tenuous.")
    with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535]), \
         patch("app.jobs.link.verify_candidates", return_value=[weak]):
        assert run_link(session) == 0
    assert session.query(PostMarket).count() == 0


def test_exhausted_budget_pauses_linking_without_error(session):
    _setup(session)
    with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535]), \
         patch("app.jobs.link.budget_remaining", return_value=0.0), \
         patch("app.jobs.link.verify_candidates") as verify:
        assert run_link(session) == 0
    verify.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_clustering.py tests/test_link_job.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.linker.clustering'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/linker/clustering.py
from datetime import timedelta
from app.models import Cluster, Post


def assign_cluster(session, post: Post, window_hours: int = 24,
                   threshold: float = 0.15) -> int:
    """Attach a post to the cluster of the nearest recent post, or start a new one."""
    if post.cluster_id is not None:
        return post.cluster_id

    cluster_id = None
    if post.embedding is not None:
        window_start = post.published_at - timedelta(hours=window_hours)
        distance = Post.embedding.cosine_distance(post.embedding).label("distance")
        neighbour = (
            session.query(Post, distance)
            .filter(Post.id != post.id)
            .filter(Post.cluster_id.isnot(None))
            .filter(Post.embedding.isnot(None))
            .filter(Post.published_at >= window_start)
            .filter(Post.published_at <= post.published_at + timedelta(hours=window_hours))
            .filter(distance <= threshold)
            .order_by(distance)
            .first()
        )
        if neighbour is not None:
            cluster_id = neighbour[0].cluster_id

    if cluster_id is None:
        cluster = Cluster(representative_post_id=post.id, post_count=0)
        session.add(cluster)
        session.flush()
        cluster_id = cluster.id

    cluster = session.get(Cluster, cluster_id)
    cluster.post_count += 1
    post.cluster_id = cluster_id
    session.commit()
    return cluster_id
```

```python
# backend/app/jobs/link.py
import logging
from datetime import datetime, timezone
from app.embeddings import embed_texts
from app.linker.clustering import assign_cluster
from app.linker.retrieval import find_candidates
from app.linker.verifier import estimate_cost, verify_candidates
from app.models import JobRun, Market, Post, PostMarket
from app.spend import budget_remaining, record_spend

logger = logging.getLogger(__name__)
MIN_CONFIDENCE = 0.55


def run_link(session, limit: int = 100) -> int:
    run = JobRun(job="link", status="running")
    session.add(run)
    session.commit()

    pending = (session.query(Post)
               .filter(Post.linked_at.is_(None))
               .order_by(Post.published_at.desc())
               .limit(limit).all())

    missing = [post for post in pending if post.embedding is None]
    if missing:
        texts = [f"{post.title}\n\n{post.body or ''}".strip() for post in missing]
        for post, vector in zip(missing, embed_texts(texts)):
            post.embedding = vector
        session.commit()

    written = 0
    for post in pending:
        assign_cluster(session, post)

        if budget_remaining(session) <= 0:
            logger.warning("daily LLM budget exhausted; pausing linking")
            break

        candidates = find_candidates(session, post)
        links = verify_candidates(post, candidates)
        record_spend(session, estimate_cost(1200, 300))

        for link in links:
            if link.confidence < MIN_CONFIDENCE:
                continue
            if session.get(PostMarket, (post.id, link.ticker)):
                continue
            market = session.get(Market, link.ticker)
            session.add(PostMarket(
                post_id=post.id, ticker=link.ticker, direction=link.direction,
                confidence=link.confidence, rationale=link.rationale,
                price_at_link=market.yes_price if market else None,
            ))
            written += 1

        post.linked_at = datetime.now(timezone.utc)
        session.commit()

    run.status = "ok"
    run.items_processed = written
    run.finished_at = datetime.now(timezone.utc)
    session.commit()
    return written
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_clustering.py tests/test_link_job.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/linker/clustering.py backend/app/jobs/link.py backend/tests/test_clustering.py backend/tests/test_link_job.py
git commit -m "feat: add linker job with clustering and confidence gating"
```

---

### Task 12: Golden-set evaluation harness

**Files:**
- Create: `backend/tests/golden/golden_set.json`
- Create: `backend/app/eval/__init__.py`
- Create: `backend/app/eval/golden.py`
- Create: `backend/tests/test_golden_eval.py`

**Interfaces:**
- Consumes: `VerifiedLink`.
- Produces:
  - `app.eval.golden.GoldenCase` — dataclass `id, title, body, expected_tickers`.
  - `app.eval.golden.load_golden_set(path) -> list[GoldenCase]`.
  - `app.eval.golden.score(predictions: dict[str, set[str]], cases: list[GoldenCase]) -> EvalResult` with fields `precision, recall, true_positives, false_positives, false_negatives`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/golden/golden_set.json` with an array of at least 5 seed cases in this shape (grow toward 40 as real data arrives):

```json
[
  {"id": "fed-cut-signal",
   "title": "Powell signals openness to a September cut as labor data softens",
   "body": "Officials see room to ease if inflation continues to cool.",
   "expected_tickers": ["FED-26SEP"]},
  {"id": "shutdown-collapse",
   "title": "Shutdown talks collapse as leadership walks out of budget meeting",
   "body": "Negotiators left without a framework.",
   "expected_tickers": ["GOVSHUT-26OCT"]},
  {"id": "celebrity-divorce",
   "title": "Pop star announces separation after four years of marriage",
   "body": "A representative confirmed the split.",
   "expected_tickers": []}
]
```

```python
# backend/tests/test_golden_eval.py
from pathlib import Path
from app.eval.golden import load_golden_set, score

GOLDEN = Path(__file__).parent / "golden" / "golden_set.json"


def test_load_golden_set_parses_cases():
    cases = load_golden_set(GOLDEN)
    assert len(cases) >= 3
    assert any(case.expected_tickers == [] for case in cases)   # a negative case exists


def test_perfect_predictions_score_one():
    cases = load_golden_set(GOLDEN)
    predictions = {case.id: set(case.expected_tickers) for case in cases}

    result = score(predictions, cases)

    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.false_positives == []


def test_a_spurious_tag_lowers_precision_and_is_reported():
    cases = load_golden_set(GOLDEN)
    predictions = {case.id: set(case.expected_tickers) for case in cases}
    predictions["celebrity-divorce"] = {"FED-26SEP"}

    result = score(predictions, cases)

    assert result.precision < 1.0
    assert ("celebrity-divorce", "FED-26SEP") in result.false_positives


def test_a_missed_market_lowers_recall():
    cases = load_golden_set(GOLDEN)
    predictions = {case.id: set(case.expected_tickers) for case in cases}
    predictions["fed-cut-signal"] = set()

    result = score(predictions, cases)

    assert result.recall < 1.0
    assert ("fed-cut-signal", "FED-26SEP") in result.false_negatives
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_golden_eval.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.eval'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/eval/golden.py
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class GoldenCase:
    id: str
    title: str
    body: str
    expected_tickers: list[str]


@dataclass
class EvalResult:
    precision: float
    recall: float
    true_positives: list[tuple[str, str]] = field(default_factory=list)
    false_positives: list[tuple[str, str]] = field(default_factory=list)
    false_negatives: list[tuple[str, str]] = field(default_factory=list)


def load_golden_set(path: Path) -> list[GoldenCase]:
    raw = json.loads(Path(path).read_text())
    return [GoldenCase(**case) for case in raw]


def score(predictions: dict[str, set[str]], cases: list[GoldenCase]) -> EvalResult:
    result = EvalResult(precision=1.0, recall=1.0)

    for case in cases:
        predicted = set(predictions.get(case.id, set()))
        expected = set(case.expected_tickers)
        result.true_positives += [(case.id, t) for t in sorted(predicted & expected)]
        result.false_positives += [(case.id, t) for t in sorted(predicted - expected)]
        result.false_negatives += [(case.id, t) for t in sorted(expected - predicted)]

    tp, fp, fn = (len(result.true_positives), len(result.false_positives),
                  len(result.false_negatives))
    result.precision = tp / (tp + fp) if (tp + fp) else 1.0
    result.recall = tp / (tp + fn) if (tp + fn) else 1.0
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_golden_eval.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/eval/ backend/tests/golden/ backend/tests/test_golden_eval.py
git commit -m "feat: add golden-set evaluation harness for link quality"
```

---

### Task 13: Impact tracker

**Files:**
- Create: `backend/app/jobs/impact.py`
- Create: `backend/tests/test_impact_job.py`

**Interfaces:**
- Consumes: `KalshiClient.fetch_candlesticks`, `PostMarket`, `Post`, `Market`.
- Produces: `app.jobs.impact.run_impact(session, client=None, now=None) -> int` — fills `price_1h` for links older than 1 hour and `price_24h` for links older than 24 hours, returns the count of fields filled.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_impact_job.py
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from app.jobs.impact import run_impact
from app.models import Market, Post, PostMarket, Source

NOW = datetime(2026, 9, 17, 18, 0, tzinfo=timezone.utc)


def _link(session, created_at, price_1h=None, price_24h=None):
    source = Source(kind="rss", name="P", feed_url="u", category="Politics")
    session.add(source)
    session.flush()
    post = Post(source_id=source.id, external_id=f"p{created_at.isoformat()}", url="u",
                title="t", published_at=created_at)
    session.add(post)
    session.add(Market(ticker="GOVSHUT-26OCT", title="q", status="open",
                       close_time=NOW + timedelta(days=20), yes_price=64,
                       volume=1, text_hash="h"))
    session.flush()
    link = PostMarket(post_id=post.id, ticker="GOVSHUT-26OCT", direction="YES",
                      confidence=0.9, rationale="r", price_at_link=53,
                      price_1h=price_1h, price_24h=price_24h, created_at=created_at)
    session.add(link)
    session.commit()
    return link


def _client(price):
    client = MagicMock()
    client.fetch_candlesticks.return_value = [(NOW, price)]
    return client


def test_fills_price_1h_for_links_older_than_an_hour(session):
    _link(session, NOW - timedelta(hours=2))

    filled = run_impact(session, client=_client(64), now=NOW)

    assert filled == 1
    assert session.query(PostMarket).one().price_1h == 64


def test_skips_links_younger_than_an_hour(session):
    _link(session, NOW - timedelta(minutes=20))

    client = _client(64)
    assert run_impact(session, client=client, now=NOW) == 0
    client.fetch_candlesticks.assert_not_called()


def test_fills_price_24h_once_a_day_has_passed(session):
    _link(session, NOW - timedelta(hours=26), price_1h=58)

    run_impact(session, client=_client(70), now=NOW)

    link = session.query(PostMarket).one()
    assert link.price_1h == 58        # untouched
    assert link.price_24h == 70


def test_already_filled_links_are_not_refetched(session):
    _link(session, NOW - timedelta(hours=30), price_1h=58, price_24h=70)

    client = _client(99)
    assert run_impact(session, client=client, now=NOW) == 0
    client.fetch_candlesticks.assert_not_called()


def test_missing_candlestick_data_is_tolerated(session):
    _link(session, NOW - timedelta(hours=2))
    client = MagicMock()
    client.fetch_candlesticks.return_value = []

    assert run_impact(session, client=client, now=NOW) == 0
    assert session.query(PostMarket).one().price_1h is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_impact_job.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.jobs.impact'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/jobs/impact.py
import logging
from datetime import datetime, timedelta, timezone
from app.clients.kalshi import KalshiClient
from app.models import JobRun, Market, PostMarket

logger = logging.getLogger(__name__)


def _price_at(client, ticker: str, series_ticker: str | None, target: datetime) -> int | None:
    points = client.fetch_candlesticks(
        ticker, target - timedelta(minutes=30), target + timedelta(minutes=30),
        series_ticker=series_ticker)
    if not points:
        return None
    return min(points, key=lambda p: abs((p[0] - target).total_seconds()))[1]


def run_impact(session, client: KalshiClient | None = None,
               now: datetime | None = None) -> int:
    client = client or KalshiClient()
    now = now or datetime.now(timezone.utc)

    run = JobRun(job="impact", status="running")
    session.add(run)
    session.commit()

    filled = 0
    links = session.query(PostMarket).filter(
        (PostMarket.price_1h.is_(None)) | (PostMarket.price_24h.is_(None))).all()

    for link in links:
        market = session.get(Market, link.ticker)
        series = market.series_ticker if market else None
        age = now - link.created_at

        for hours, attribute in ((1, "price_1h"), (24, "price_24h")):
            if getattr(link, attribute) is not None or age < timedelta(hours=hours):
                continue
            try:
                price = _price_at(client, link.ticker, series,
                                  link.created_at + timedelta(hours=hours))
            except Exception as exc:
                logger.warning("candlestick fetch failed for %s: %s", link.ticker, exc)
                continue
            if price is not None:
                setattr(link, attribute, price)
                filled += 1

    session.commit()
    run.status = "ok"
    run.items_processed = filled
    run.finished_at = datetime.now(timezone.utc)
    session.commit()
    return filled
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_impact_job.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/jobs/impact.py backend/tests/test_impact_job.py
git commit -m "feat: add price impact tracker"
```

---

### Task 14: Read API and authenticated job endpoints

**Files:**
- Create: `backend/app/schemas.py`
- Create: `backend/app/api.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/test_api.py`
- Create: `.github/workflows/jobs.yml`

**Interfaces:**
- Consumes: every job function and model.
- Produces:
  - `GET /api/feed?category=&limit=&cursor=` → `{"items": [FeedItem], "next_cursor": str | None}`
  - `GET /api/posts/{post_id}` → `PostDetail`
  - `GET /api/trending?limit=` → `{"by_volume": [TrendingMarket], "most_covered": [TrendingMarket]}`
  - `POST /api/jobs/{job_name}` guarded by an `X-Job-Token` header matching `settings.job_token`; `job_name` ∈ `{sync_markets, ingest, link, impact}`.
  - `GET /health` → `{"status": "ok"}`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_api.py
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models import Market, Post, PostMarket, Source

NOW = datetime.now(timezone.utc)


def _seed(session):
    source = Source(kind="rss", name="Politico", feed_url="u", category="Politics")
    session.add(source)
    session.flush()
    post = Post(source_id=source.id, external_id="p1", url="https://politico.com/a",
                title="Shutdown talks collapse", body="Leadership walked out.",
                author_name="Politico", category="Politics", published_at=NOW)
    session.add(post)
    session.add(Market(ticker="GOVSHUT-26OCT", title="Shutdown before Oct 15?",
                       rules_summary="Resolves YES on a lapse.", category="Politics",
                       status="open", close_time=NOW + timedelta(days=28),
                       yes_price=64, volume=2400000, text_hash="h"))
    session.flush()
    session.add(PostMarket(post_id=post.id, ticker="GOVSHUT-26OCT", direction="YES",
                           confidence=0.86, rationale="No path to a deal remains.",
                           price_at_link=53, price_1h=64))
    session.commit()
    return post


def test_feed_returns_posts_newest_first_with_their_markets(session):
    _seed(session)
    response = TestClient(app).get("/api/feed")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["title"] == "Shutdown talks collapse"
    assert item["author_name"] == "Politico"
    assert item["markets"][0]["ticker"] == "GOVSHUT-26OCT"
    assert item["markets"][0]["direction"] == "YES"
    assert item["markets"][0]["price_delta"] == 11      # 64 - 53


def test_feed_filters_by_category(session):
    _seed(session)
    client = TestClient(app)

    assert len(client.get("/api/feed?category=Politics").json()["items"]) == 1
    assert client.get("/api/feed?category=Sports").json()["items"] == []


def test_post_detail_includes_body_and_rationales(session):
    post = _seed(session)
    payload = TestClient(app).get(f"/api/posts/{post.id}").json()

    assert payload["body"] == "Leadership walked out."
    assert payload["url"] == "https://politico.com/a"
    assert payload["markets"][0]["rationale"] == "No path to a deal remains."
    assert payload["markets"][0]["kalshi_url"].startswith("https://kalshi.com/markets/")


def test_unknown_post_returns_404(session):
    assert TestClient(app).get("/api/posts/999999").status_code == 404


def test_trending_returns_both_rankings(session):
    _seed(session)
    payload = TestClient(app).get("/api/trending").json()

    assert payload["by_volume"][0]["ticker"] == "GOVSHUT-26OCT"
    assert payload["most_covered"][0]["post_count"] == 1


def test_job_endpoint_requires_the_token(session):
    client = TestClient(app)

    assert client.post("/api/jobs/ingest").status_code == 401
    assert client.post("/api/jobs/ingest", headers={"X-Job-Token": "wrong"}).status_code == 401


def test_job_endpoint_runs_the_named_job(session, monkeypatch):
    monkeypatch.setenv("JOB_TOKEN", "secret")
    from app.config import get_settings
    get_settings.cache_clear()

    with patch("app.api.run_ingest", return_value=7) as job:
        response = TestClient(app).post("/api/jobs/ingest", headers={"X-Job-Token": "secret"})

    assert response.status_code == 200
    assert response.json() == {"job": "ingest", "items_processed": 7}
    job.assert_called_once()


def test_unknown_job_name_returns_404(session, monkeypatch):
    monkeypatch.setenv("JOB_TOKEN", "secret")
    from app.config import get_settings
    get_settings.cache_clear()

    response = TestClient(app).post("/api/jobs/nope", headers={"X-Job-Token": "secret"})
    assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/schemas.py
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


class FeedPage(BaseModel):
    items: list[FeedItem]
    next_cursor: str | None = None
```

```python
# backend/app/api.py
from datetime import datetime
from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import func
from app.config import get_settings
from app.db import get_session
from app.jobs.impact import run_impact
from app.jobs.ingest import run_ingest
from app.jobs.link import run_link
from app.jobs.sync_markets import sync_markets
from app.models import Cluster, Market, Post, PostMarket
from app.schemas import FeedItem, FeedPage, MarketRef, PostDetail, TrendingMarket

router = APIRouter()

JOBS = {"sync_markets": sync_markets, "ingest": run_ingest,
        "link": run_link, "impact": run_impact}

UTM = "?utm_source=kalshi-news&utm_medium=referral&utm_campaign=feed"


def kalshi_url(ticker: str) -> str:
    return f"https://kalshi.com/markets/{ticker}{UTM}"


def _market_refs(session, post: Post) -> list[MarketRef]:
    rows = (session.query(PostMarket, Market)
            .join(Market, Market.ticker == PostMarket.ticker)
            .filter(PostMarket.post_id == post.id)
            .order_by(PostMarket.confidence.desc()).all())
    refs = []
    for link, market in rows:
        latest = link.price_24h if link.price_24h is not None else link.price_1h
        delta = (latest - link.price_at_link
                 if latest is not None and link.price_at_link is not None else None)
        refs.append(MarketRef(
            ticker=market.ticker, title=market.title, direction=link.direction,
            confidence=link.confidence, rationale=link.rationale,
            yes_price=market.yes_price, volume=market.volume,
            close_time=market.close_time, price_delta=delta,
            kalshi_url=kalshi_url(market.ticker)))
    return refs


def _to_item(session, post: Post, model=FeedItem):
    cluster = session.get(Cluster, post.cluster_id) if post.cluster_id else None
    payload = dict(
        id=post.id, title=post.title, url=post.url, author_name=post.author_name,
        author_handle=post.author_handle, avatar_url=post.avatar_url,
        source_kind=post.source.kind, category=post.category,
        published_at=post.published_at,
        cluster_size=cluster.post_count if cluster else 1,
        markets=_market_refs(session, post))
    if model is PostDetail:
        payload["body"] = post.body
    return model(**payload)


@router.get("/api/feed", response_model=FeedPage)
def feed(category: str | None = None, limit: int = Query(30, le=100),
         cursor: str | None = None):
    with get_session() as session:
        query = session.query(Post).order_by(Post.published_at.desc())
        if category:
            query = query.filter(Post.category == category)
        if cursor:
            query = query.filter(Post.published_at < datetime.fromisoformat(cursor))
        posts = query.limit(limit).all()
        items = [_to_item(session, post) for post in posts]
        next_cursor = posts[-1].published_at.isoformat() if len(posts) == limit else None
        return FeedPage(items=items, next_cursor=next_cursor)


@router.get("/api/posts/{post_id}", response_model=PostDetail)
def post_detail(post_id: int):
    with get_session() as session:
        post = session.get(Post, post_id)
        if post is None:
            raise HTTPException(status_code=404, detail="post not found")
        return _to_item(session, post, model=PostDetail)


@router.get("/api/trending")
def trending(limit: int = Query(10, le=50)):
    with get_session() as session:
        by_volume = (session.query(Market)
                     .filter(Market.status == "open")
                     .order_by(Market.volume.desc().nullslast())
                     .limit(limit).all())
        covered = (session.query(Market, func.count(PostMarket.post_id).label("n"))
                   .join(PostMarket, PostMarket.ticker == Market.ticker)
                   .group_by(Market.ticker).order_by(func.count(PostMarket.post_id).desc())
                   .limit(limit).all())
        return {
            "by_volume": [TrendingMarket(
                ticker=m.ticker, title=m.title, yes_price=m.yes_price,
                volume=m.volume, kalshi_url=kalshi_url(m.ticker)) for m in by_volume],
            "most_covered": [TrendingMarket(
                ticker=m.ticker, title=m.title, yes_price=m.yes_price, volume=m.volume,
                post_count=n, kalshi_url=kalshi_url(m.ticker)) for m, n in covered],
        }


@router.post("/api/jobs/{job_name}")
def run_job(job_name: str, x_job_token: str | None = Header(default=None)):
    expected = get_settings().job_token
    if not expected or x_job_token != expected:
        raise HTTPException(status_code=401, detail="bad job token")
    job = JOBS.get(job_name)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job")
    with get_session() as session:
        return {"job": job_name, "items_processed": job(session)}
```

```python
# backend/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import router

app = FastAPI(title="Kalshi News API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_api.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Add the cron workflow**

```yaml
# .github/workflows/jobs.yml
name: Scheduled jobs
on:
  schedule:
    - cron: "*/15 * * * *"   # sync_markets
    - cron: "*/10 * * * *"   # ingest + link
    - cron: "17 * * * *"     # impact
  workflow_dispatch:

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - name: Sync markets
        if: github.event.schedule == '*/15 * * * *' || github.event_name == 'workflow_dispatch'
        run: |
          curl -sS -f -X POST "$API_URL/api/jobs/sync_markets" \
            -H "X-Job-Token: $JOB_TOKEN"
        env:
          API_URL: ${{ secrets.API_URL }}
          JOB_TOKEN: ${{ secrets.JOB_TOKEN }}
      - name: Ingest then link
        if: github.event.schedule == '*/10 * * * *' || github.event_name == 'workflow_dispatch'
        run: |
          curl -sS -f -X POST "$API_URL/api/jobs/ingest" -H "X-Job-Token: $JOB_TOKEN"
          curl -sS -f -X POST "$API_URL/api/jobs/link"   -H "X-Job-Token: $JOB_TOKEN"
        env:
          API_URL: ${{ secrets.API_URL }}
          JOB_TOKEN: ${{ secrets.JOB_TOKEN }}
      - name: Impact
        if: github.event.schedule == '17 * * * *' || github.event_name == 'workflow_dispatch'
        run: |
          curl -sS -f -X POST "$API_URL/api/jobs/impact" -H "X-Job-Token: $JOB_TOKEN"
        env:
          API_URL: ${{ secrets.API_URL }}
          JOB_TOKEN: ${{ secrets.JOB_TOKEN }}
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas.py backend/app/api.py backend/app/main.py backend/tests/test_api.py .github/workflows/jobs.yml
git commit -m "feat: add read API, job endpoints, and cron workflows"
```

---

## Self-Review Notes

**Spec coverage.** Kalshi sync → Task 5. RSS ingestion → Task 6. X discovery/oEmbed/permanent cache → Tasks 7-8. Retrieval → Task 9. Haiku verification, structured output, retry, spend cap → Task 10. Clustering, confidence gating, price snapshot → Task 11. Golden set → Task 12. Impact tracker → Task 13. Read API, UTM attribution, job auth, cron → Task 14. Per-source isolation → Task 8. Idempotency → Tasks 5, 8, 11, 13.

**Deferred to the frontend plan:** the feed UI, centered post view, trending rail, wordmark, newsletter signup endpoint, and the daily digest job. The `subscribers` table exists from Task 2 so no migration is needed when that work starts.

**Not yet covered anywhere, by design:** the `relink` nightly job. It is a refinement of Task 11 that matters only once the catalog is churning, and it is tracked as a follow-up rather than blocking the first working pipeline.
