import logging
from datetime import UTC, datetime, timedelta

from app.ingest.rss import RssIngestor
from app.ingest.x import XIngestor, extract_tweet_ids
from app.models import JobRun, Post, Source

logger = logging.getLogger(__name__)
LOOKBACK = timedelta(hours=6)


def _default_ingestors():
    return {"rss": RssIngestor(), "x": XIngestor()}


def _ingest_source(session, source, ingestor, since, discovered_tweet_ids, seen_tweet_ids
                    ) -> tuple[int, bool]:
    """Fetch and store one source's posts. Returns (stored_count, succeeded).

    Fetching, storing and committing are all inside the same guarded block so
    a failure at any stage -- a network error during fetch, or a bad row
    during store/commit -- is isolated to this source: the exception is
    logged, the session is rolled back so it stays usable for the sources
    that follow, and nothing propagates out.
    """
    # Captured before anything risky: a failed flush expires every object in
    # the session, and reading an expired attribute (e.g. source.name) while
    # the transaction is still in its post-failure "needs rollback" state
    # triggers a *second*, unhandled error that would defeat this isolation.
    source_name = source.name
    try:
        raw_posts = ingestor.fetch(source, since)

        # Snapshot of external_ids already stored for this source, extended
        # in-memory as new posts are queued this batch -- mirrors the pattern
        # sync_markets.py uses for tickers, and avoids relying on a
        # per-item DB re-query (and its autoflush timing) to catch
        # duplicate external_ids returned within a single fetch.
        known_external_ids = {
            row[0] for row in
            session.query(Post.external_id).filter_by(source_id=source.id).all()
        }

        stored = 0
        for raw in raw_posts:
            if source.kind != "x" and raw.body:
                for tweet_id in extract_tweet_ids(raw.body):
                    if tweet_id not in seen_tweet_ids:
                        seen_tweet_ids.add(tweet_id)
                        discovered_tweet_ids.append(tweet_id)

            if raw.external_id in known_external_ids:
                continue
            known_external_ids.add(raw.external_id)

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
                published_at=raw.published_at or datetime.now(UTC),
            ))
            stored += 1

        session.commit()
        return stored, True
    except Exception as exc:                       # isolate per source
        session.rollback()
        logger.warning("source %s failed: %s", source_name, exc)
        return 0, False


def run_ingest(session, ingestors: dict | None = None) -> int:
    # An ingestor dict built here (nothing injected) is this job's own to
    # close. A caller-injected dict (tests inject mocks) is not ours to
    # close -- mirrors the KalshiClient ownership rule in sync_markets.py
    # and impact.py.
    owns_ingestors = ingestors is None
    ingestors = ingestors or _default_ingestors()
    run = JobRun(job="ingest", status="running")
    session.add(run)
    session.commit()

    since = datetime.now(UTC) - LOOKBACK
    stored = 0
    failed_sources: list[str] = []

    # Discovered tweet IDs, order-preserving and deduped across the whole run.
    discovered_tweet_ids: list[str] = []
    seen_tweet_ids: set[str] = set()

    try:
        sources = session.query(Source).filter_by(enabled=True).order_by(Source.id).all()
        # RSS (and other non-X) sources run first so their article text can
        # seed tweet discovery before any X source runs. This is a structural
        # partition by kind, not an accident of id ordering.
        non_x_sources = [s for s in sources if s.kind != "x"]
        x_sources = [s for s in sources if s.kind == "x"]
        x_source_ids = [s.id for s in x_sources]

        for source in non_x_sources:
            ingestor = ingestors.get(source.kind)
            if ingestor is None:
                continue
            count, succeeded = _ingest_source(
                session, source, ingestor, since, discovered_tweet_ids, seen_tweet_ids
            )
            stored += count
            if not succeeded:
                failed_sources.append(source.name)

        for source in x_sources:
            ingestor = ingestors.get(source.kind)
            if ingestor is None:
                continue
            # Run-wide, freshly queried before each X source: catches tweets
            # already stored by an earlier X source in this same run (once
            # its commit lands) as well as ones stored in a prior run, so a
            # tweet is hydrated exactly once across every X source, not just
            # within one.
            already_stored = {
                row[0] for row in
                session.query(Post.external_id).filter(Post.source_id.in_(x_source_ids)).all()
            }
            source.pending_tweet_ids = [
                tweet_id for tweet_id in discovered_tweet_ids if tweet_id not in already_stored
            ]
            count, succeeded = _ingest_source(
                session, source, ingestor, since, discovered_tweet_ids, seen_tweet_ids
            )
            stored += count
            if not succeeded:
                failed_sources.append(source.name)
    finally:
        # Always reach a terminal status, even if something above this line
        # (outside a single source's guarded block) raises unexpectedly.
        run.status = "error" if failed_sources else "ok"
        if failed_sources:
            run.error = "failed sources: " + ", ".join(failed_sources)
        run.items_processed = stored
        run.finished_at = datetime.now(UTC)
        session.commit()
        if owns_ingestors:
            for ingestor in ingestors.values():
                ingestor.close()

    return stored
