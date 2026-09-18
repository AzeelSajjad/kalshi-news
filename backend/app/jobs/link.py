import logging
from datetime import UTC, datetime, timedelta

from app.embeddings import embed_texts
from app.linker.clustering import assign_cluster
from app.linker.retrieval import find_candidates
from app.linker.verifier import VerificationError, estimate_cost, verify_candidates
from app.models import JobRun, Market, Post, PostMarket
from app.spend import budget_remaining, record_spend

logger = logging.getLogger(__name__)
MIN_CONFIDENCE = 0.55

# A post that matched nothing stays pending (see _link_post), so the pending
# set needs a ceiling or it grows for the life of the deployment and every run
# re-embeds and re-retrieves the whole archive. 48h matches the spec's
# re-linking window: past that, a post is old news and not worth a retry.
PENDING_WINDOW = timedelta(hours=48)


def cluster_representative(session, post: Post) -> Post | None:
    """The already-linked post that speaks for this post's cluster, if any.

    The spec renders a cluster as one card with a "+N sources" chip and links
    it once; Task 11's Interfaces block says run_link "links cluster
    representatives". Six outlets carrying one story must therefore cost one
    Haiku call, not six identical ones producing six identical cards.

    A post that reached no candidates is deliberately *not* eligible: it has
    linked_at IS NULL (see _link_post) and carries no links to copy.
    """
    if post.cluster_id is None:
        return None
    return (
        session.query(Post)
        .filter(Post.cluster_id == post.cluster_id)
        .filter(Post.id != post.id)
        .filter(Post.linked_at.isnot(None))
        .order_by(Post.linked_at)
        .first()
    )


def _copy_links(session, post: Post, representative: Post) -> int:
    """Duplicate the representative's post_markets rows onto this post.

    The rationale and confidence are the cluster's verdict on the story, not
    on one outlet's wording, so they carry over verbatim. price_at_link comes
    across too: it is the price when this story broke, which is the same
    moment for every outlet in the cluster. price_1h/price_24h are left empty
    -- the impact job fills those per row against this row's own created_at.
    """
    written = 0
    existing = (
        session.query(PostMarket)
        .filter(PostMarket.post_id == representative.id)
        .order_by(PostMarket.confidence.desc())
        .all()
    )
    for link in existing:
        if session.get(PostMarket, (post.id, link.ticker)):
            continue
        session.add(PostMarket(
            post_id=post.id, ticker=link.ticker, direction=link.direction,
            confidence=link.confidence, rationale=link.rationale,
            price_at_link=link.price_at_link,
        ))
        written += 1
    return written


def _link_post(session, post: Post, representative: Post | None = None) -> tuple[int, bool]:
    """Retrieve candidates, verify, and write PostMarket rows for one post.

    When `representative` is given, the post's cluster has already been
    linked: its rows are copied instead of paying for a second identical
    LLM call.

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
        if representative is not None:
            written = _copy_links(session, post, representative)
            post.linked_at = datetime.now(UTC)
            session.commit()
            return written, True

        candidates = find_candidates(session, post)
        try:
            result = verify_candidates(post, candidates)
        except VerificationError as exc:
            # attempt 1 (or later) was a real, billed call even though this
            # call never returns a VerificationResult -- record it before
            # letting the failure fall through to per-post isolation below.
            # Zero tokens means the very first attempt failed before any
            # usage was billed, so there is nothing to record.
            if exc.input_tokens or exc.output_tokens:
                record_spend(session, estimate_cost(exc.input_tokens, exc.output_tokens))
            raise

        # No candidates means verify_candidates short-circuited without an
        # LLM call -- (links=[], input_tokens=0, output_tokens=0) by
        # construction -- and most posts match nothing, so recording spend
        # unconditionally here would run a pointless SELECT + UPDATE +
        # COMMIT on the large majority of posts. A billed call that simply
        # found nothing related still has nonzero tokens and must still be
        # recorded (see test_spend_is_recorded_even_when_the_verifier_finds_
        # nothing_related).
        if result.input_tokens or result.output_tokens:
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

        # Only a post that actually reached the verifier is retired. An empty
        # candidate list means retrieval found nothing *yet* -- no LLM call was
        # made and nothing was learned, so stamping linked_at would be a
        # permanent tombstone: run_link selects only linked_at IS NULL and
        # nothing ever clears it. The cron runs link every 10 minutes and
        # sync_markets every 15, so on a cold deploy the first link run fires
        # before a single market exists; that batch would render untagged for
        # the life of the deployment. Leaving it pending costs nothing:
        # verify_candidates returns early on an empty candidate list, so the
        # retry is retrieval only.
        if candidates:
            post.linked_at = datetime.now(UTC)
        session.commit()
        return written, True
    except Exception as exc:                       # isolate per post
        session.rollback()
        logger.warning("post %s failed to link: %s", post.id, exc)
        return 0, False


def run_link(session, limit: int = 15) -> int:
    """Embed, cluster, and link unlinked posts to markets.

    The default limit is deliberately small. Each post is a Haiku round trip
    of a few seconds and the job runs synchronously inside the HTTP request
    that GitHub Actions' curl makes, so a large batch would simply time out.
    At 15 per run, every 10 minutes, the job clears 2160 posts/day -- well
    above the ~800/day the spec projects.

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
            .filter(Post.published_at > datetime.now(UTC) - PENDING_WINDOW)
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
            representative = cluster_representative(session, post)

            # A cluster-mate's links are copied, not re-derived, so this post
            # makes no LLM call and must not be held up by an exhausted
            # budget -- that would strand it unlinked next to an identical,
            # tagged sibling in the feed.
            if representative is None and budget_remaining(session) <= 0:
                logger.warning("daily LLM budget exhausted; pausing linking")
                budget_paused = True
                break

            links_written, succeeded = _link_post(session, post, representative)
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
