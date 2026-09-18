from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.jobs.link import run_link
from app.linker.verifier import VerificationError, VerificationResult, VerifiedLink
from app.models import JobRun, LlmSpend, Market, Post, PostMarket, Source

NOW = datetime.now(UTC)


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


def _result(links, input_tokens=1200, output_tokens=300):
    return VerificationResult(links=links, input_tokens=input_tokens, output_tokens=output_tokens)


def test_link_writes_post_markets_with_price_snapshot(session):
    _setup(session)
    with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535]), \
         patch("app.jobs.link.verify_candidates", return_value=_result([LINK])):
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
         patch("app.jobs.link.verify_candidates", return_value=_result([LINK])) as verify:
        run_link(session)
        run_link(session)

    assert verify.call_count == 1
    assert session.query(PostMarket).count() == 1


def test_low_confidence_links_are_dropped(session):
    _setup(session)
    weak = VerifiedLink(ticker="GOVSHUT-26OCT", related=True, direction="YES",
                        confidence=0.20, rationale="Tenuous.")
    with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535]), \
         patch("app.jobs.link.verify_candidates", return_value=_result([weak])):
        assert run_link(session) == 0
    assert session.query(PostMarket).count() == 0
    # The post must still be marked linked -- otherwise it would be
    # re-selected (linked_at IS NULL) and re-verified, and re-billed, on
    # every future run forever.
    assert session.query(Post).one().linked_at is not None
    # The verifier call that produced the (rejected) weak link was still a
    # real, billed call and must still be metered against the daily cap.
    spend_row = session.query(LlmSpend).one()
    assert spend_row.usd > 0


def test_spend_is_recorded_even_when_the_verifier_finds_nothing_related(session):
    # result.links can legitimately be empty (nothing the verifier judged
    # related survived _parse_links) while the call itself was still real
    # and billed -- guarding record_spend behind `if result.links:` would
    # silently stop metering this case, so this must not be conflated with
    # the "no candidates -> no call -> nothing to bill" case.
    _setup(session)
    with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535]), \
         patch("app.jobs.link.verify_candidates",
               return_value=_result([], input_tokens=800, output_tokens=200)), \
         patch("app.jobs.link.estimate_cost", wraps=lambda i, o: i + o) as cost:
        written = run_link(session)

    assert written == 0
    cost.assert_called_once_with(800, 200)
    spend_row = session.query(LlmSpend).one()
    assert spend_row.usd > 0
    assert session.query(Post).one().linked_at is not None


def test_exhausted_budget_pauses_linking_without_error(session):
    _setup(session)
    with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535]), \
         patch("app.jobs.link.budget_remaining", return_value=0.0), \
         patch("app.jobs.link.verify_candidates") as verify:
        assert run_link(session) == 0
    verify.assert_not_called()
    # The post is left untagged so a later run (once the budget refills)
    # picks it back up.
    assert session.query(Post).one().linked_at is None
    run = session.query(JobRun).filter_by(job="link").one()
    # A pause is not an error, but it must be distinguishable from a run
    # that simply had nothing left to do.
    assert run.status == "ok"
    assert run.error == "daily LLM budget exhausted"


def test_budget_is_rechecked_before_every_post_not_once_per_run(session):
    _setup(session)
    source = session.query(Source).one()
    # A distinct published_at pins the DESC ordering so which post is
    # "first" (budget available) vs. "second" (budget exhausted) is
    # deterministic rather than an unspecified tie-break.
    session.add(Post(source_id=source.id, external_id="p2", url="u2",
                     title="Second shutdown story", published_at=NOW - timedelta(minutes=1)))
    session.commit()

    # Two *different* stories: identical embeddings would put both posts in
    # one cluster, and the second would then copy the first's links without
    # an LLM call (and without a budget check), which is not what this test
    # is about. An orthogonal vector keeps them in separate clusters.
    with patch("app.jobs.link.embed_texts",
               return_value=[[1.0] + [0.0] * 1535, [0.0, 1.0] + [0.0] * 1534]), \
         patch("app.jobs.link.budget_remaining", side_effect=[1.0, 0.0]), \
         patch("app.jobs.link.verify_candidates", return_value=_result([LINK])) as verify:
        written = run_link(session)

    assert verify.call_count == 1
    assert written == 1
    first, second = (session.query(Post).filter_by(external_id=eid).one()
                     for eid in ("p1", "p2"))
    assert first.linked_at is not None
    assert second.linked_at is None


def test_real_token_usage_is_recorded_not_a_hardcoded_estimate(session):
    _setup(session)
    with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535]), \
         patch("app.jobs.link.verify_candidates",
               return_value=_result([LINK], input_tokens=4000, output_tokens=900)), \
         patch("app.jobs.link.estimate_cost", wraps=lambda i, o: i + o) as cost:
        run_link(session)

    cost.assert_called_once_with(4000, 900)


def test_embedding_failure_marks_job_run_as_error_and_does_not_raise(session):
    _setup(session)
    with patch("app.jobs.link.embed_texts", side_effect=RuntimeError("openai outage")), \
         patch("app.jobs.link.verify_candidates") as verify:
        written = run_link(session)

    assert written == 0
    verify.assert_not_called()
    run = session.query(JobRun).filter_by(job="link").one()
    assert run.status == "error"
    assert "openai outage" in run.error
    assert run.finished_at is not None
    # The session must still be usable after the failure.
    assert session.query(Post).count() == 1


def test_one_failing_post_does_not_stop_linking_of_others(session):
    _setup(session)
    source = session.query(Source).one()
    session.add(Post(source_id=source.id, external_id="p2", url="u2",
                     title="Second shutdown story", published_at=NOW - timedelta(minutes=1)))
    session.commit()

    # p1 sorts first (DESC by published_at) and its verify call raises;
    # p2 must still get linked rather than the whole run aborting at p1 --
    # and p1 must stay unlinked so it is retried, not silently dropped.
    with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535] * 2), \
         patch("app.jobs.link.verify_candidates",
               side_effect=[RuntimeError("boom"), _result([LINK])]):
        written = run_link(session)

    assert written == 1
    assert session.query(PostMarket).count() == 1
    first, second = (session.query(Post).filter_by(external_id=eid).one()
                     for eid in ("p1", "p2"))
    assert first.linked_at is None
    assert second.linked_at is not None

    run = session.query(JobRun).filter_by(job="link").one()
    assert run.status == "error"
    assert "failed posts" in run.error
    assert str(first.id) in run.error


def test_verification_error_still_records_spend_for_the_billed_attempt(session):
    _setup(session)
    err = VerificationError("provider outage on retry", input_tokens=700, output_tokens=150)
    with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535]), \
         patch("app.jobs.link.verify_candidates", side_effect=err), \
         patch("app.jobs.link.estimate_cost", wraps=lambda i, o: i + o) as cost:
        written = run_link(session)

    assert written == 0
    cost.assert_called_once_with(700, 150)
    spend_row = session.query(LlmSpend).one()
    assert spend_row.usd > 0
    run = session.query(JobRun).filter_by(job="link").one()
    assert run.status == "error"
    assert "failed posts" in run.error


def test_duplicate_ticker_in_one_response_is_not_double_written(session):
    _setup(session)
    duplicate = [LINK, LINK]
    # Autoflush is turned off deliberately. The DB-lookup guard
    # (session.get(PostMarket, ...)) would only see a same-iteration
    # pending row if it happened to trigger an autoflush first -- with
    # autoflush off, that guard sees nothing, so this proves it is the
    # in-memory `seen_tickers` set (not autoflush timing) that keeps the
    # duplicate ticker from being staged twice and hitting the composite
    # primary key on commit.
    session.autoflush = False
    try:
        with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535]), \
             patch("app.jobs.link.verify_candidates", return_value=_result(duplicate)):
            written = run_link(session)
    finally:
        session.autoflush = True

    assert written == 1
    assert session.query(PostMarket).count() == 1
    run = session.query(JobRun).filter_by(job="link").one()
    assert run.status == "ok"


def test_written_count_excludes_links_lost_to_a_failed_commit(session):
    _setup(session)
    # This ticker has no matching Market row, so the FK constraint on
    # post_markets.ticker fails at commit time -- after `written` would
    # already have been incremented inside the loop. The returned total
    # (and items_processed) must not count a row a rollback erased.
    bad_link = VerifiedLink(ticker="NOT-A-REAL-MARKET", related=True, direction="YES",
                            confidence=0.9, rationale="Bogus ticker forces a commit failure.")
    with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535]), \
         patch("app.jobs.link.verify_candidates", return_value=_result([bad_link])):
        written = run_link(session)

    assert written == 0
    assert session.query(PostMarket).count() == 0
    run = session.query(JobRun).filter_by(job="link").one()
    assert run.items_processed == 0
    assert run.status == "error"


def test_job_run_recorded_as_ok_on_success(session):
    _setup(session)
    with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535]), \
         patch("app.jobs.link.verify_candidates", return_value=_result([LINK])):
        run_link(session)

    run = session.query(JobRun).filter_by(job="link").one()
    assert run.status == "ok"
    assert run.items_processed == 1
    assert run.finished_at is not None


def test_a_post_that_matched_no_markets_stays_pending(session):
    """linked_at must not become a permanent tombstone.

    run_link only ever selects linked_at IS NULL and nothing clears it, so
    stamping a post that reached no candidates -- and therefore made no LLM
    call and learned nothing -- retires it forever. The cron runs link every
    10 minutes and sync_markets every 15, so on a cold deploy the first link
    run fires before a single market exists; that whole batch would render
    untagged for the life of the deployment.

    Re-retrieving these posts costs nothing: verify_candidates returns early
    on an empty candidate list, so no Anthropic call is made.
    """
    source = Source(kind="rss", name="Politico", feed_url="u", category="Politics")
    session.add(source)
    session.flush()
    session.add(Post(source_id=source.id, external_id="p1", url="u",
                     title="Shutdown talks collapse", published_at=NOW))
    session.commit()                      # deliberately: not one Market row exists

    with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535]), \
         patch("app.jobs.link.verify_candidates", return_value=_result([], 0, 0)) as verify:
        assert run_link(session) == 0

    assert verify.call_args.args[1] == []
    assert session.query(Post).one().linked_at is None


def test_pending_posts_are_bounded_to_the_last_48_hours(session):
    """Posts that matched nothing stay pending, so the pending set needs a
    ceiling or it grows without limit and eventually every run re-embeds and
    re-retrieves the entire archive."""
    _setup(session)
    source = session.query(Source).one()
    session.add(Post(source_id=source.id, external_id="ancient", url="u2",
                     title="Old shutdown story", published_at=NOW - timedelta(days=3)))
    session.commit()

    with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535]), \
         patch("app.jobs.link.verify_candidates", return_value=_result([LINK])) as verify:
        run_link(session)

    assert verify.call_count == 1
    ancient = session.query(Post).filter_by(external_id="ancient").one()
    assert ancient.linked_at is None
    assert session.query(PostMarket).filter_by(post_id=ancient.id).count() == 0


def test_two_posts_in_one_cluster_cost_one_llm_call_and_share_its_tags(session):
    """The spec renders a cluster as one card with '+N sources' and links it
    once. Six outlets on one story must not mean six identical Haiku calls
    and six identical sets of tags computed from scratch."""
    _setup(session)
    source = session.query(Source).one()
    session.add(Post(source_id=source.id, external_id="p2", url="u2",
                     title="Shutdown talks break down, sources say",
                     published_at=NOW - timedelta(minutes=1)))
    session.commit()

    # Identical embeddings put both posts in one cluster (assign_cluster's
    # threshold is a cosine distance of 0.15).
    vector = [1.0] + [0.0] * 1535
    with patch("app.jobs.link.embed_texts", return_value=[vector, vector]), \
         patch("app.jobs.link.verify_candidates", return_value=_result([LINK])) as verify:
        written = run_link(session)

    assert verify.call_count == 1, "the cluster's second post paid for its own LLM call"
    assert written == 2

    first, second = (session.query(Post).filter_by(external_id=eid).one()
                     for eid in ("p1", "p2"))
    assert first.cluster_id == second.cluster_id
    assert second.linked_at is not None
    for post in (first, second):
        links = session.query(PostMarket).filter_by(post_id=post.id).all()
        assert [link.ticker for link in links] == ["GOVSHUT-26OCT"]
        assert links[0].direction == "YES"
        assert links[0].rationale == LINK.rationale


def test_a_run_is_capped_so_it_fits_inside_the_http_request(session):
    """run_link is executed synchronously inside the job endpoint's request
    and each post is a multi-second Haiku round trip, so the batch has to be
    small enough to finish before the cron's curl gives up. At 15 per run
    every 10 minutes the job still clears 2160 posts/day."""
    _setup(session)
    source = session.query(Source).one()
    for i in range(20):
        session.add(Post(source_id=source.id, external_id=f"bulk{i}", url=f"u{i}",
                         title=f"Shutdown story {i}",
                         published_at=NOW - timedelta(minutes=i + 1)))
    session.commit()

    vector = [1.0] + [0.0] * 1535
    with patch("app.jobs.link.embed_texts", side_effect=lambda texts: [vector] * len(texts)), \
         patch("app.jobs.link.verify_candidates", return_value=_result([LINK])):
        run_link(session)

    assert session.query(Post).filter(Post.linked_at.isnot(None)).count() == 15
