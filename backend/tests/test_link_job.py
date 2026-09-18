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

    # Budget is fine for the first post, exhausted by the second.
    with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535] * 2), \
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
