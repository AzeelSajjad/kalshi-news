from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.jobs.link import run_link
from app.linker.verifier import VerificationResult, VerifiedLink
from app.models import JobRun, Market, Post, PostMarket, Source

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


def test_budget_is_rechecked_before_every_post_not_once_per_run(session):
    _setup(session)
    source = session.query(Source).one()
    session.add(Post(source_id=source.id, external_id="p2", url="u2",
                     title="Second shutdown story", published_at=NOW))
    session.commit()

    # Budget is fine for the first post, exhausted by the second.
    with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535] * 2), \
         patch("app.jobs.link.budget_remaining", side_effect=[1.0, 0.0]), \
         patch("app.jobs.link.verify_candidates", return_value=_result([LINK])) as verify:
        written = run_link(session)

    assert verify.call_count == 1
    assert written == 1
    linked = [p.linked_at is not None for p in session.query(Post).all()]
    assert linked.count(True) == 1


def test_real_token_usage_is_recorded_not_a_hardcoded_estimate(session):
    _setup(session)
    with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535]), \
         patch("app.jobs.link.verify_candidates",
               return_value=_result([LINK], input_tokens=4000, output_tokens=900)), \
         patch("app.jobs.link.estimate_cost", wraps=lambda i, o: i + o) as cost:
        run_link(session)

    cost.assert_called_once_with(4000, 900)


def test_verifier_failure_marks_job_run_as_error_and_does_not_raise(session):
    _setup(session)
    with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535]), \
         patch("app.jobs.link.verify_candidates", side_effect=RuntimeError("anthropic outage")):
        written = run_link(session)

    assert written == 0
    run = session.query(JobRun).filter_by(job="link").one()
    assert run.status == "error"
    assert "anthropic outage" in run.error
    assert run.finished_at is not None
    # The session must still be usable after the failure.
    assert session.query(Post).count() == 1


def test_job_run_recorded_as_ok_on_success(session):
    _setup(session)
    with patch("app.jobs.link.embed_texts", return_value=[[1.0] + [0.0] * 1535]), \
         patch("app.jobs.link.verify_candidates", return_value=_result([LINK])):
        run_link(session)

    run = session.query(JobRun).filter_by(job="link").one()
    assert run.status == "ok"
    assert run.items_processed == 1
    assert run.finished_at is not None
