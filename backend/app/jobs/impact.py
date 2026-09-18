import logging
from datetime import UTC, datetime, timedelta

from app.clients.kalshi import KalshiClient
from app.models import JobRun, Market, PostMarket

logger = logging.getLogger(__name__)


def _price_at(client: KalshiClient, ticker: str, series_ticker: str | None,
              target: datetime) -> int | None:
    points = client.fetch_candlesticks(
        ticker, target - timedelta(minutes=30), target + timedelta(minutes=30),
        series_ticker=series_ticker)
    if not points:
        return None
    return min(points, key=lambda p: abs((p[0] - target).total_seconds()))[1]


def run_impact(session, client: KalshiClient | None = None,
                now: datetime | None = None) -> int:
    """Fill price_1h/price_24h for PostMarket links old enough to have them.

    Mirrors run_ingest/run_link's shape: a JobRun always reaches a terminal
    status via try/except/finally, and a failure fetching one link's
    candlesticks is isolated to that link (logged, skipped) rather than
    aborting the run -- the analogue of per-source/per-post isolation in
    those jobs.

    Idempotent: only links missing price_1h or price_24h are selected, and
    within that set only the still-empty, old-enough field is fetched -- an
    already-filled field is never re-fetched, and a link younger than an
    hour is skipped entirely (no fetch at all).
    """
    client = client or KalshiClient()
    now = now or datetime.now(UTC)

    run = JobRun(job="impact", status="running")
    session.add(run)
    session.commit()

    filled = 0
    failed_tickers: list[str] = []
    error_message: str | None = None
    try:
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
                except Exception as exc:              # isolate per link
                    logger.warning("candlestick fetch failed for %s: %s", link.ticker, exc)
                    failed_tickers.append(link.ticker)
                    continue
                if price is not None:
                    setattr(link, attribute, price)
                    filled += 1

        session.commit()
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

    return filled
