import logging
from datetime import UTC, datetime

from app.embeddings import embed_texts
from app.linker.clustering import assign_cluster
from app.linker.retrieval import find_candidates
from app.linker.verifier import estimate_cost, verify_candidates
from app.models import JobRun, Market, Post, PostMarket
from app.spend import budget_remaining, record_spend

logger = logging.getLogger(__name__)
MIN_CONFIDENCE = 0.55


def run_link(session, limit: int = 100) -> int:
    """Embed, cluster, and link unlinked posts to markets.

    The body runs inside a try/except/finally so an OpenAI or Anthropic
    outage mid-job cannot leave the JobRun row stranded at status='running'.
    On failure the session is rolled back (so it stays usable for the
    caller) and the run is recorded with status='error' and a message,
    mirroring the pattern in app/jobs/ingest.py.
    """
    run = JobRun(job="link", status="running")
    session.add(run)
    session.commit()

    written = 0
    error_message: str | None = None
    try:
        pending = (
            session.query(Post)
            .filter(Post.linked_at.is_(None))
            .order_by(Post.published_at.desc())
            .limit(limit)
            .all()
        )

        missing = [post for post in pending if post.embedding is None]
        if missing:
            texts = [f"{post.title}\n\n{post.body or ''}".strip() for post in missing]
            for post, vector in zip(missing, embed_texts(texts), strict=True):
                post.embedding = vector
            session.commit()

        for post in pending:
            assign_cluster(session, post)

            if budget_remaining(session) <= 0:
                logger.warning("daily LLM budget exhausted; pausing linking")
                break

            candidates = find_candidates(session, post)
            result = verify_candidates(post, candidates)
            record_spend(session, estimate_cost(result.input_tokens, result.output_tokens))

            for link in result.links:
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

            post.linked_at = datetime.now(UTC)
            session.commit()
    except Exception as exc:                       # keep the JobRun terminal
        session.rollback()
        error_message = str(exc)
        logger.exception("link job failed: %s", exc)
    finally:
        run.status = "error" if error_message else "ok"
        run.error = error_message
        run.items_processed = written
        run.finished_at = datetime.now(UTC)
        session.commit()

    return written
