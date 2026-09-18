import logging
from datetime import UTC, datetime

from app.embeddings import embed_texts
from app.linker.clustering import assign_cluster
from app.linker.retrieval import find_candidates
from app.linker.verifier import VerificationError, estimate_cost, verify_candidates
from app.models import JobRun, Market, Post, PostMarket
from app.spend import budget_remaining, record_spend

logger = logging.getLogger(__name__)
MIN_CONFIDENCE = 0.55


def _link_post(session, post: Post) -> tuple[int, bool]:
    """Retrieve candidates, verify, and write PostMarket rows for one post.

    Isolated per post the way _ingest_source isolates per source in
    app/jobs/ingest.py: any failure here -- a malformed verifier response
    that raises VerificationError, a transport error, an IntegrityError on
    commit -- is caught, the session is rolled back so it stays usable for
    the posts that follow, and the failure is reported via the returned
    flag instead of propagating. Without this, one poison post would end
    the run at that point on every future run, since it stays selected by
    the linked_at IS NULL query and nothing behind it ever gets a turn.

    Returns (links_written, succeeded). links_written only reflects rows
    that made it through a successful commit -- if the commit itself fails,
    the caller must not count them.
    """
    try:
        candidates = find_candidates(session, post)
        try:
            result = verify_candidates(post, candidates)
        except VerificationError as exc:
            # attempt 1 (or later) was a real, billed call even though this
            # call never returns a VerificationResult -- record it before
            # letting the failure fall through to per-post isolation below.
            record_spend(session, estimate_cost(exc.input_tokens, exc.output_tokens))
            raise

        record_spend(session, estimate_cost(result.input_tokens, result.output_tokens))

        written = 0
        seen_tickers: set[str] = set()
        for link in result.links:
            if link.confidence < MIN_CONFIDENCE:
                continue
            if link.ticker in seen_tickers:
                continue
            seen_tickers.add(link.ticker)
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
        return written, True
    except Exception as exc:                       # isolate per post
        session.rollback()
        logger.warning("post %s failed to link: %s", post.id, exc)
        return 0, False


def run_link(session, limit: int = 100) -> int:
    """Embed, cluster, and link unlinked posts to markets.

    The body runs inside a try/except/finally so the JobRun always reaches
    a terminal status -- mirroring app/jobs/ingest.py's run_ingest. Failures
    while retrieving/embedding the batch (outside any single post's turn)
    are caught here and mark the whole run 'error'; failures while linking
    one specific post are isolated in _link_post and only that post is
    named as failed, the way ingest.py names failed sources.
    """
    run = JobRun(job="link", status="running")
    session.add(run)
    session.commit()

    written = 0
    failed_post_ids: list[int] = []
    budget_paused = False
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
                budget_paused = True
                break

            links_written, succeeded = _link_post(session, post)
            written += links_written
            if not succeeded:
                failed_post_ids.append(post.id)
    except Exception as exc:
        session.rollback()
        error_message = str(exc)
        logger.exception("link job failed: %s", exc)
    finally:
        if error_message:
            run.status = "error"
            run.error = error_message
        elif failed_post_ids:
            run.status = "error"
            run.error = "failed posts: " + ", ".join(str(pid) for pid in failed_post_ids)
        else:
            run.status = "ok"
            # A budget pause is not an error, but an operator needs a way to
            # tell a run that paused early apart from one that finished the
            # whole batch.
            run.error = "daily LLM budget exhausted" if budget_paused else None
        run.items_processed = written
        run.finished_at = datetime.now(UTC)
        session.commit()

    return written
