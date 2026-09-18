import logging
from datetime import UTC, datetime

from app.clients.kalshi import KalshiClient, KalshiMarket
from app.embeddings import embed_texts
from app.market_text import compose_market_text, text_hash
from app.models import JobRun, Market

logger = logging.getLogger(__name__)

# The catalog is upserted in chunks, each committed on its own, so one bad
# row (an over-long ticker, a malformed close_time) costs that chunk rather
# than the entire catalog -- the analogue of per-source isolation in
# run_ingest and per-post isolation in run_link.
CHUNK_SIZE = 200


def _sync_chunk(session, chunk: list[KalshiMarket]) -> tuple[int, bool]:
    """Upsert one chunk of the catalog and commit it. Returns (count, succeeded).

    Each chunk re-reads the rows it is about to touch instead of sharing a
    dict across the whole run: that keeps chunks independent, so a rollback
    in one cannot leave a detached or expired Market object behind for a
    later chunk to write through.
    """
    # Captured before anything risky: a failed flush expires every object in
    # the session, and reading an ORM attribute while the transaction is
    # still in its post-failure "needs rollback" state raises a second,
    # unhandled error that would defeat this isolation.
    tickers = [incoming.ticker for incoming in chunk]
    try:
        existing = {
            market.ticker: market
            for market in session.query(Market).filter(Market.ticker.in_(tickers)).all()
        }
        needs_embedding: list[tuple[Market, str]] = []

        for incoming in chunk:
            composed = compose_market_text(incoming)
            digest = text_hash(composed)
            market = existing.get(incoming.ticker)

            if market is None:
                market = Market(ticker=incoming.ticker)
                session.add(market)
                existing[incoming.ticker] = market

            market.event_ticker = incoming.event_ticker
            market.series_ticker = incoming.series_ticker
            market.title = incoming.title
            market.rules_summary = incoming.rules_summary
            market.category = incoming.category
            # Stored as Kalshi reports it ("active" for a live market) and
            # kept for display/debugging only. Nothing filters on it -- see
            # the note in app/linker/retrieval.py.
            market.status = incoming.status
            market.close_time = incoming.close_time
            market.yes_price = incoming.yes_price
            market.volume = incoming.volume
            market.updated_at = datetime.now(UTC)

            if market.text_hash != digest:
                market.text_hash = digest
                needs_embedding.append((market, composed))

        vectors = embed_texts([text for _, text in needs_embedding])
        for (market, _), vector in zip(needs_embedding, vectors):
            market.embedding = vector

        session.commit()
        return len(chunk), True
    except Exception as exc:                       # isolate per chunk
        session.rollback()
        logger.warning("market chunk %s..%s failed: %s", tickers[0], tickers[-1], exc)
        return 0, False


def sync_markets(session, client: KalshiClient | None = None) -> int:
    """Mirror Kalshi's public market catalog into `markets`.

    Wrapped in the same try/except/finally + JobRun shell the other three
    jobs use, so a Kalshi outage or a bad row leaves a terminal `job_runs`
    row to look at rather than vanishing into an HTTP 500.
    """
    # A client constructed here (nothing injected) is this job's own to
    # close. A caller-injected client (tests inject mocks; a future caller
    # might share one client across jobs) is not ours to close.
    owns_client = client is None
    client = client or KalshiClient()

    run = JobRun(job="sync_markets", status="running")
    session.add(run)
    session.commit()

    synced = 0
    failed_chunks = 0
    error_message: str | None = None
    try:
        fetched = client.fetch_all_markets()
        for start in range(0, len(fetched), CHUNK_SIZE):
            count, succeeded = _sync_chunk(session, fetched[start:start + CHUNK_SIZE])
            synced += count
            if not succeeded:
                failed_chunks += 1
    except Exception as exc:
        session.rollback()
        error_message = str(exc)
        logger.exception("sync_markets failed: %s", exc)
    finally:
        if error_message:
            run.status = "error"
            run.error = error_message
        elif failed_chunks:
            run.status = "error"
            run.error = f"{failed_chunks} market chunk(s) failed"
        else:
            run.status = "ok"
        run.items_processed = synced
        run.finished_at = datetime.now(UTC)
        session.commit()
        if owns_client:
            client.close()

    return synced
