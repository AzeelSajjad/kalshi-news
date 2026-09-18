from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from app.jobs.impact import run_impact
from app.models import JobRun, Market, Post, PostMarket, Source

NOW = datetime(2026, 9, 17, 18, 0, tzinfo=UTC)


def _link(session, created_at, price_1h=None, price_24h=None):
    source = Source(kind="rss", name="P", feed_url="u", category="Politics")
    session.add(source)
    session.flush()
    post = Post(source_id=source.id, external_id=f"p{created_at.isoformat()}-{source.id}",
                url="u", title="t", published_at=created_at)
    session.add(post)
    if session.get(Market, "GOVSHUT-26OCT") is None:
        session.add(Market(ticker="GOVSHUT-26OCT", title="q", status="open",
                           close_time=NOW + timedelta(days=20), yes_price=64,
                           volume=1, text_hash="h"))
    session.flush()
    link = PostMarket(post_id=post.id, ticker="GOVSHUT-26OCT", direction="YES",
                      confidence=0.9, rationale="r", price_at_link=53,
                      price_1h=price_1h, price_24h=price_24h, created_at=created_at)
    session.add(link)
    session.commit()
    return link


def _client(price):
    client = MagicMock()
    client.fetch_candlesticks.return_value = [(NOW, price)]
    return client


def test_fills_price_1h_for_links_older_than_an_hour(session):
    _link(session, NOW - timedelta(hours=2))

    filled = run_impact(session, client=_client(64), now=NOW)

    assert filled == 1
    assert session.query(PostMarket).one().price_1h == 64


def test_skips_links_younger_than_an_hour(session):
    _link(session, NOW - timedelta(minutes=20))

    client = _client(64)
    assert run_impact(session, client=client, now=NOW) == 0
    client.fetch_candlesticks.assert_not_called()


def test_fills_price_24h_once_a_day_has_passed(session):
    _link(session, NOW - timedelta(hours=26), price_1h=58)

    run_impact(session, client=_client(70), now=NOW)

    link = session.query(PostMarket).one()
    assert link.price_1h == 58        # untouched
    assert link.price_24h == 70


def test_already_filled_links_are_not_refetched(session):
    _link(session, NOW - timedelta(hours=30), price_1h=58, price_24h=70)

    client = _client(99)
    assert run_impact(session, client=client, now=NOW) == 0
    client.fetch_candlesticks.assert_not_called()


def test_missing_candlestick_data_is_tolerated(session):
    _link(session, NOW - timedelta(hours=2))
    client = MagicMock()
    client.fetch_candlesticks.return_value = []

    assert run_impact(session, client=client, now=NOW) == 0
    assert session.query(PostMarket).one().price_1h is None


def test_fills_both_when_link_is_at_least_a_day_old(session):
    _link(session, NOW - timedelta(hours=26))

    filled = run_impact(session, client=_client(66), now=NOW)

    link = session.query(PostMarket).one()
    assert filled == 2
    assert link.price_1h == 66
    assert link.price_24h == 66


def test_link_exactly_one_hour_old_is_filled(session):
    _link(session, NOW - timedelta(hours=1))

    filled = run_impact(session, client=_client(61), now=NOW)

    assert filled == 1
    assert session.query(PostMarket).one().price_1h == 61


def test_per_link_fetch_failure_does_not_abort_run(session):
    _link(session, NOW - timedelta(hours=2))
    _link(session, NOW - timedelta(hours=2))

    client = MagicMock()
    client.fetch_candlesticks.side_effect = [Exception("boom"), [(NOW, 61)]]

    filled = run_impact(session, client=client, now=NOW)

    assert filled == 1
    prices = sorted(
        (row.price_1h for row in session.query(PostMarket).all()),
        key=lambda v: (v is None, v),
    )
    assert prices == [61, None]


def test_earlier_links_persist_when_a_later_links_commit_fails(session, monkeypatch):
    """Regression test: run_impact must commit per link, not once for the whole run.

    Two links are processed in order (impact.py orders by created_at). The
    *second* commit issued by the job -- the first link's own commit, since
    the run's own JobRun row consumes the first -- is made to raise. Before
    this fix, a single end-of-run commit meant that failure would roll back
    every fill computed in the run, including the first link's, which had
    nothing to do with the failure. After the fix, each link commits on its
    own, so the first link's fill survives even though a later commit fails.
    """
    first = _link(session, NOW - timedelta(hours=2))
    second = _link(session, NOW - timedelta(hours=1, minutes=30))

    real_commit = session.commit
    call_count = {"n": 0}

    def flaky_commit():
        call_count["n"] += 1
        if call_count["n"] == 2:  # the first link's own commit
            raise RuntimeError("simulated commit failure")
        return real_commit()

    monkeypatch.setattr(session, "commit", flaky_commit)

    filled = run_impact(session, client=_client(64), now=NOW)

    # Query fresh rows -- not the possibly-stale in-memory `first`/`second`.
    persisted_first = session.get(PostMarket, (first.post_id, first.ticker))
    persisted_second = session.get(PostMarket, (second.post_id, second.ticker))

    assert persisted_first.price_1h is None          # its commit failed: not persisted
    assert persisted_second.price_1h == 64            # a later link's commit still landed
    assert filled == 1                                 # only the persisted fill is counted


def test_items_processed_reflects_only_persisted_fills_after_partial_failure(session, monkeypatch):
    """items_processed on the JobRun row must match what's actually in the DB,
    not an in-memory count that includes fills whose commit later failed."""
    _link(session, NOW - timedelta(hours=2))
    _link(session, NOW - timedelta(hours=1, minutes=30))

    real_commit = session.commit
    call_count = {"n": 0}

    def flaky_commit():
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated commit failure")
        return real_commit()

    monkeypatch.setattr(session, "commit", flaky_commit)

    run_impact(session, client=_client(64), now=NOW)

    actual_persisted = sum(
        1 for row in session.query(PostMarket).all() if row.price_1h is not None
    )
    run = session.query(JobRun).filter_by(job="impact").order_by(JobRun.id.desc()).first()
    assert run.items_processed == actual_persisted == 1


def test_market_lookup_failure_is_isolated_to_its_own_link(session, monkeypatch):
    """A failure looking up the Market row for one link (a DB hiccup, e.g.)
    must be isolated to that link -- not escape and abort the whole run, the
    way a candlestick-fetch failure is already isolated."""
    first = _link(session, NOW - timedelta(hours=2))
    second = _link(session, NOW - timedelta(hours=1, minutes=30))

    real_get = session.get
    call_count = {"n": 0}

    def flaky_get(model, ident):
        if model is Market:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("simulated market lookup failure")
        return real_get(model, ident)

    monkeypatch.setattr(session, "get", flaky_get)

    filled = run_impact(session, client=_client(64), now=NOW)

    persisted_first = session.get(PostMarket, (first.post_id, first.ticker))
    persisted_second = session.get(PostMarket, (second.post_id, second.ticker))
    assert persisted_first.price_1h is None    # its Market lookup raised: isolated
    assert persisted_second.price_1h == 64     # the next link still gets processed
    assert filled == 1
