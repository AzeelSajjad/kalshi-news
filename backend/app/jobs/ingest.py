import logging
from datetime import UTC, datetime, timedelta

from app.ingest.rss import RssIngestor
from app.ingest.x import XIngestor, extract_tweet_ids
from app.models import JobRun, Post, Source

logger = logging.getLogger(__name__)
LOOKBACK = timedelta(hours=6)


def _default_ingestors():
    return {"rss": RssIngestor(), "x": XIngestor()}


def _ingest_source(session, source, ingestor, since, discovered_tweet_ids, seen_tweet_ids) -> int:
    try:
        raw_posts = ingestor.fetch(source, since)
    except Exception as exc:                       # isolate per source
        logger.warning("source %s failed: %s", source.name, exc)
        return 0

    stored = 0
    for raw in raw_posts:
        if source.kind != "x" and raw.body:
            for tweet_id in extract_tweet_ids(raw.body):
                if tweet_id not in seen_tweet_ids:
                    seen_tweet_ids.add(tweet_id)
                    discovered_tweet_ids.append(tweet_id)

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
            published_at=raw.published_at or datetime.now(UTC),
        ))
        stored += 1
    session.commit()
    return stored


def run_ingest(session, ingestors: dict | None = None) -> int:
    ingestors = ingestors or _default_ingestors()
    run = JobRun(job="ingest", status="running")
    session.add(run)
    session.commit()

    since = datetime.now(UTC) - LOOKBACK
    stored = 0

    # Discovered tweet IDs, order-preserving and deduped across the whole run.
    discovered_tweet_ids: list[str] = []
    seen_tweet_ids: set[str] = set()

    sources = session.query(Source).filter_by(enabled=True).order_by(Source.id).all()
    # RSS (and other non-X) sources run first so their article text can seed
    # tweet discovery before any X source runs.
    non_x_sources = [s for s in sources if s.kind != "x"]
    x_sources = [s for s in sources if s.kind == "x"]

    for source in non_x_sources:
        ingestor = ingestors.get(source.kind)
        if ingestor is None:
            continue
        stored += _ingest_source(
            session, source, ingestor, since, discovered_tweet_ids, seen_tweet_ids
        )

    for source in x_sources:
        ingestor = ingestors.get(source.kind)
        if ingestor is None:
            continue
        already_stored = {
            row[0] for row in
            session.query(Post.external_id).filter_by(source_id=source.id).all()
        }
        source.pending_tweet_ids = [
            tweet_id for tweet_id in discovered_tweet_ids if tweet_id not in already_stored
        ]
        stored += _ingest_source(
            session, source, ingestor, since, discovered_tweet_ids, seen_tweet_ids
        )

    run.status = "ok"
    run.items_processed = stored
    run.finished_at = datetime.now(UTC)
    session.commit()
    return stored
