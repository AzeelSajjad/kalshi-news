import logging
from datetime import UTC, datetime, timedelta

from app.clients.kalshi import KalshiClient
from app.models import JobRun, Market, PostMarket

logger = logging.getLogger(__name__)
RETRY_WINDOW = timedelta(hours=72)


def _price_at(client: KalshiClient, ticker: str, series_ticker: str | None,
              target: datetime) -> int | None:
    points = client.fetch_candlesticks(
        ticker, target - timedelta(minutes=30), target + timedelta(minutes=30),
        series_ticker=series_ticker)
    if not points:
        return None
    return min(points, key=lambda p: abs((p[0] - target).total_seconds()))[1]


def _process_link(session, client: KalshiClient, link: PostMarket,
                   now: datetime) -> tuple[int, bool]:
    """Fetch and persist price snapshots for one link. Returns (filled, succeeded).

    Isolated per link the way _ingest_source isolates per source in
    app/jobs/ingest.py and _link_post isolates per post in app/jobs/link.py:
    the *entire* per-link body -- the Market lookup as well as the
    candlestick fetch -- sits inside the guarded block, and this link commits
    on its own. A failure here (a bad Market lookup, a candlestick fetch
    error, an IntegrityError on commit) is caught, the session is rolled
    back so it stays usable for the links that follow, and only this link's
    work is lost -- an earlier link's already-committed fill is untouched.

    `filled` is only ever returned on the success path, after this link's
    own commit has actually landed, so a caller summing these counts (for
    JobRun.items_processed) never reports a fill that didn't persist.

    The ticker is captured before the guarded block, not read from `link`
    inside the except -- mirroring _ingest_source's capture of source_name.
    After a rollback, reading an ORM attribute off `link` can trigger an
    implicit refresh that itself raises, escaping past this function's own
    error handling.
    """
    ticker = link.ticker
    try:
        market = session.get(Market, ticker)
        series = market.series_ticker if market else None
        age = now - link.created_at

        filled = 0
        for hours, attribute in ((1, "price_1h"), (24, "price_24h")):
            if getattr(link, attribute) is not None or age < timedelta(hours=hours):
                continue
            price = _price_at(client, ticker, series, link.created_at + timedelta(hours=hours))
            if price is not None:
                setattr(link, attribute, price)
                filled += 1

        session.commit()
        return filled, True
    except Exception as exc:                          # isolate per link
        session.rollback()
        logger.warning("impact fetch failed for %s: %s", ticker, exc)
        return 0, False


def run_impact(session, client: KalshiClient | None = None,
                now: datetime | None = None) -> int:
    """Fill price_1h/price_24h for PostMarket links old enough to have them.

    Mirrors run_ingest/run_link's shape: a JobRun always reaches a terminal
    status via try/except/finally, and each link is processed (and
    committed) independently by _process_link, so a failure on one link is
    isolated -- the analogue of per-source/per-post isolation in those jobs.

    Idempotent: only links missing price_1h or price_24h are selected, and
    within that set only the still-empty, old-enough field is fetched -- an
    already-filled field is never re-fetched, and a link younger than an
    hour is skipped entirely (no fetch at all).
    """
    # Mirrors sync_markets.py: only close a client this call constructed
    # itself, never one the caller injected.
    owns_client = client is None
    client = client or KalshiClient()
    now = now or datetime.now(UTC)

    run = JobRun(job="impact", status="running")
    session.add(run)
    session.commit()

    filled = 0
    failed_tickers: list[str] = []
    error_message: str | None = None
    try:
        # A link whose market never produced candlesticks (thin or brand-new
        # markets often have none) can never be filled, and without a ceiling
        # on created_at it was re-fetched every hour forever -- a Kalshi
        # request per dead link per hour, growing for the life of the
        # deployment. 72h is a full day of slack past the 24h snapshot.
        links = (
            session.query(PostMarket)
            .filter((PostMarket.price_1h.is_(None)) | (PostMarket.price_24h.is_(None)))
            .filter(PostMarket.created_at > now - RETRY_WINDOW)
            .order_by(PostMarket.created_at)
            .all()
        )

        for link in links:
            ticker = link.ticker            # captured before this link's guarded work
            link_filled, succeeded = _process_link(session, client, link, now)
            filled += link_filled
            if not succeeded:
                failed_tickers.append(ticker)
    except Exception as exc:
        session.rollback()
        error_message = str(exc)
        logger.exception("impact job failed: %s", exc)
    finally:
        if error_message:
            run.status = "error"
            run.error = error_message
        elif failed_tickers:
            run.status = "error"
            run.error = "failed links: " + ", ".join(failed_tickers)
        else:
            run.status = "ok"
        run.items_processed = filled
        run.finished_at = datetime.now(UTC)
        session.commit()
        if owns_client:
            client.close()

    return filled
