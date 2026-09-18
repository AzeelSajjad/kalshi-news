import logging
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException, Query
from sqlalchemy import func, tuple_
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db import get_session
from app.jobs.impact import run_impact
from app.jobs.ingest import run_ingest
from app.jobs.link import run_link
from app.jobs.sync_markets import sync_markets
from app.models import Cluster, Market, Post, PostMarket
from app.schemas import (
    FeedItem,
    FeedPage,
    JobResult,
    MarketRef,
    PostDetail,
    TrendingMarket,
    TrendingPage,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Late-bound on purpose: a dict of {"ingest": run_ingest, ...} built at import
# time would capture the function objects themselves, so patching
# `app.api.run_ingest` in a test would never affect what JOBS calls. Lambdas
# defer the lookup of `run_ingest` (etc.) to call time, resolving it against
# this module's current globals -- which is what a patch actually replaces.
JOBS = {
    "sync_markets": lambda s: sync_markets(s),
    "ingest": lambda s: run_ingest(s),
    "link": lambda s: run_link(s),
    "impact": lambda s: run_impact(s),
}

UTM = "?utm_source=kalshi-news&utm_medium=referral&utm_campaign=feed"


def kalshi_url(ticker: str) -> str:
    return f"https://kalshi.com/markets/{ticker}{UTM}"


def _encode_cursor(post: Post) -> str:
    """A keyset cursor: (published_at, id) instead of a bare timestamp.

    A bare timestamp cursor with strict '<' silently and permanently drops
    posts that share a published_at with the last item on a page (RSS feeds
    routinely round to the minute; a batch ingest can stamp many posts
    identically). Pairing the timestamp with the tie-broken, always-unique
    id makes the ordering total, so every post is reachable exactly once.
    """
    return f"{post.published_at.isoformat()}|{post.id}"


def _decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        ts_part, id_part = cursor.rsplit("|", 1)
        post_id = int(id_part)
        ts = datetime.fromisoformat(ts_part)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="invalid cursor") from exc
    if ts.tzinfo is None:
        # Comparing a naive datetime against a timestamptz column silently
        # reinterprets it in the session's timezone -- contradicts the
        # tz-aware-UTC rule the rest of the codebase follows, so reject it
        # outright rather than let it produce a wrong, un-flagged answer.
        raise HTTPException(
            status_code=422, detail="cursor timestamp must be timezone-aware"
        )
    return ts, post_id


def _price_delta(link: PostMarket) -> int | None:
    latest = link.price_24h if link.price_24h is not None else link.price_1h
    if latest is None or link.price_at_link is None:
        return None
    return latest - link.price_at_link


def _load_market_refs(session: Session, post_ids: list[int]) -> dict[int, list[MarketRef]]:
    """One query for the whole page, not one per post.

    A per-post query (session.query(PostMarket, Market).filter(post_id=...))
    would turn an N-item feed page into N round trips. Instead we fetch every
    link+market row whose post_id is in this page in a single IN-query and
    group the results in Python.
    """
    if not post_ids:
        return {}
    rows = (
        session.query(PostMarket, Market)
        .join(Market, Market.ticker == PostMarket.ticker)
        .filter(PostMarket.post_id.in_(post_ids))
        .order_by(PostMarket.post_id, PostMarket.confidence.desc())
        .all()
    )
    refs: dict[int, list[MarketRef]] = {}
    for link, market in rows:
        refs.setdefault(link.post_id, []).append(
            MarketRef(
                ticker=market.ticker,
                title=market.title,
                direction=link.direction,
                confidence=link.confidence,
                rationale=link.rationale,
                yes_price=market.yes_price,
                volume=market.volume,
                close_time=market.close_time,
                price_delta=_price_delta(link),
                kalshi_url=kalshi_url(market.ticker),
            )
        )
    return refs


def _load_cluster_sizes(session: Session, cluster_ids: list[int]) -> dict[int, int]:
    """One query for the whole page instead of one Cluster lookup per post."""
    ids = [cid for cid in cluster_ids if cid is not None]
    if not ids:
        return {}
    clusters = session.query(Cluster).filter(Cluster.id.in_(ids)).all()
    return {cluster.id: cluster.post_count for cluster in clusters}


def _assemble_items(
    session: Session, posts: list[Post], model: type[FeedItem] = FeedItem
) -> list[FeedItem]:
    """Build response items for a page of posts using pre-batched lookups.

    Markets and cluster sizes for the whole `posts` list are each fetched in
    a single query up front (see _load_market_refs / _load_cluster_sizes),
    so this function does no further querying per post. `post.source` is
    expected to already be eager-loaded (via selectinload) on the query that
    produced `posts`, so `post.source.kind` below is also not a per-post
    round trip.
    """
    post_ids = [post.id for post in posts]
    market_refs = _load_market_refs(session, post_ids)
    cluster_sizes = _load_cluster_sizes(session, [post.cluster_id for post in posts])

    items = []
    for post in posts:
        payload = dict(
            id=post.id,
            title=post.title,
            url=post.url,
            author_name=post.author_name,
            author_handle=post.author_handle,
            avatar_url=post.avatar_url,
            source_kind=post.source.kind,
            category=post.category,
            published_at=post.published_at,
            cluster_size=cluster_sizes.get(post.cluster_id, 1),
            markets=market_refs.get(post.id, []),
        )
        if model is PostDetail:
            payload["body"] = post.body
        items.append(model(**payload))
    return items


@router.get("/api/feed", response_model=FeedPage)
def feed(
    category: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    cursor: str | None = None,
):
    with get_session() as session:
        query = (
            session.query(Post)
            .options(selectinload(Post.source))
            .order_by(Post.published_at.desc(), Post.id.desc())
        )
        if category:
            query = query.filter(Post.category == category)
        if cursor:
            cursor_ts, cursor_id = _decode_cursor(cursor)
            query = query.filter(
                tuple_(Post.published_at, Post.id) < tuple_(cursor_ts, cursor_id)
            )
        # Fetch one extra row so we know whether another page follows
        # without a second COUNT query, and so an exactly-full page doesn't
        # emit a next_cursor that leads to an empty page.
        rows = query.limit(limit + 1).all()
        has_more = len(rows) > limit
        posts = rows[:limit]
        items = _assemble_items(session, posts, model=FeedItem)
        next_cursor = _encode_cursor(posts[-1]) if has_more else None
        return FeedPage(items=items, next_cursor=next_cursor)


@router.get("/api/posts/{post_id}", response_model=PostDetail)
def post_detail(post_id: int):
    with get_session() as session:
        post = (
            session.query(Post)
            .options(selectinload(Post.source))
            .filter(Post.id == post_id)
            .one_or_none()
        )
        if post is None:
            raise HTTPException(status_code=404, detail="post not found")
        return _assemble_items(session, [post], model=PostDetail)[0]


@router.get("/api/trending", response_model=TrendingPage)
def trending(limit: int = Query(10, ge=1, le=50)):
    with get_session() as session:
        now = datetime.now(UTC)
        # status alone is not trustworthy: Kalshi stops returning settled
        # markets from its open feed, so a settled market's row can keep
        # status='open' forever. close_time is the real authority, and
        # find_candidates() (app/linker/retrieval.py) already filters on
        # both together -- trending must agree or the sidebar surfaces
        # markets that have already closed.
        by_volume = (
            session.query(Market)
            .filter(Market.status == "open")
            .filter(Market.close_time > now)
            .order_by(Market.volume.desc().nulls_last())
            .limit(limit)
            .all()
        )
        covered = (
            session.query(Market, func.count(PostMarket.post_id).label("n"))
            .join(PostMarket, PostMarket.ticker == Market.ticker)
            .filter(Market.status == "open")
            .filter(Market.close_time > now)
            .group_by(Market.ticker)
            .order_by(func.count(PostMarket.post_id).desc())
            .limit(limit)
            .all()
        )
        return TrendingPage(
            by_volume=[
                TrendingMarket(
                    ticker=m.ticker,
                    title=m.title,
                    yes_price=m.yes_price,
                    volume=m.volume,
                    kalshi_url=kalshi_url(m.ticker),
                )
                for m in by_volume
            ],
            most_covered=[
                TrendingMarket(
                    ticker=m.ticker,
                    title=m.title,
                    yes_price=m.yes_price,
                    volume=m.volume,
                    post_count=n,
                    kalshi_url=kalshi_url(m.ticker),
                )
                for m, n in covered
            ],
        )


@router.post("/api/jobs/{job_name}", response_model=JobResult)
def run_job(job_name: str, x_job_token: str | None = Header(default=None)):
    expected = get_settings().job_token
    # Fail closed: an unconfigured (blank) job_token must reject every
    # request rather than accept any. `not expected` covers that case
    # explicitly instead of relying on `"" != x_job_token` happening to work.
    # secrets.compare_digest instead of `!=` for the actual comparison: not
    # a real exposure over an ASGI stack, but a no-downside upgrade.
    if not expected or not x_job_token or not secrets.compare_digest(x_job_token, expected):
        raise HTTPException(status_code=401, detail="bad job token")
    job = JOBS.get(job_name)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job")
    with get_session() as session:
        try:
            items_processed = job(session)
        except Exception as exc:
            # The jobs themselves already record their own JobRun rows and
            # isolate per-item failures internally (see app/jobs/*.py); a
            # raise here means something failed before or outside that
            # isolation (e.g. sync_markets' initial Kalshi fetch). Don't add
            # retry logic -- just don't let it escape as an opaque 500
            # traceback.
            # type(exc).__name__ only, not str(exc): a SQLAlchemy error can
            # carry the failing SQL and connection metadata in its message.
            # logger.exception already captured the full detail server-side.
            logger.exception("job %s failed", job_name)
            raise HTTPException(
                status_code=500, detail=f"job {job_name} failed: {type(exc).__name__}"
            ) from exc
        return JobResult(job=job_name, items_processed=items_processed)
