from datetime import UTC, datetime, timedelta

from app.linker.retrieval import find_candidates
from app.models import Market, Post, Source

NOW = datetime.now(UTC)


def _vec(value: float):
    return [value] + [0.0] * 1535


def _market(session, ticker, value, status="open", close_in_days=30):
    session.add(Market(
        ticker=ticker, title=f"{ticker} question?", rules_summary="Resolves YES.",
        category="Economics", status=status, close_time=NOW + timedelta(days=close_in_days),
        yes_price=50, volume=1000, text_hash=ticker, embedding=_vec(value)))


def _post(session, value: float) -> Post:
    source = Source(kind="rss", name="R", feed_url="u", category="Economics")
    session.add(source)
    session.flush()
    post = Post(source_id=source.id, external_id=f"e{value}", url="u", title="t",
                published_at=NOW, embedding=_vec(value))
    session.add(post)
    session.commit()
    return post


def test_returns_nearest_markets_ordered_by_distance(session):
    # Inserted in the opposite of the expected result order, so a missing
    # ORDER BY (which would otherwise fall back to insertion/scan order)
    # cannot accidentally produce the right answer.
    _market(session, "FAR", -1.0)
    _market(session, "NEAR", 1.0)
    post = _post(session, 1.0)

    candidates = find_candidates(session, post, limit=10, max_distance=2.0)

    assert [c.ticker for c in candidates] == ["NEAR", "FAR"]
    assert candidates[0].distance < candidates[1].distance


def test_excludes_markets_whose_close_time_has_passed(session):
    """close_time is the sole liveness filter. A settled market is excluded
    because Kalshi stops returning it from the open feed (so it stops being
    refreshed) and because its close_time is in the past -- not because of
    anything read off the status column, which is advisory only.
    """
    _market(session, "EXPIRED", 1.0, close_in_days=-1)
    _market(session, "GOOD", 1.0)
    post = _post(session, 1.0)

    assert [c.ticker for c in find_candidates(session, post, max_distance=2.0)] == ["GOOD"]


def test_distance_floor_filters_out_weak_matches(session):
    _market(session, "FAR", -1.0)
    post = _post(session, 1.0)

    assert find_candidates(session, post, max_distance=0.5) == []


def test_post_without_embedding_returns_nothing(session):
    _market(session, "ANY", 1.0)
    source = Source(kind="rss", name="R", feed_url="u", category="Economics")
    session.add(source)
    session.flush()
    post = Post(source_id=source.id, external_id="none", url="u", title="t", published_at=NOW)
    session.add(post)
    session.commit()

    assert find_candidates(session, post) == []


def test_a_market_synced_with_kalshis_own_status_value_is_still_a_candidate(session):
    """Kalshi's /markets response reports a live market as status "active",
    not "open" -- filtering candidates on status == "open" made the linker
    inert against every real synced row while every hand-built test row
    (status="open") kept passing. close_time is the authority for whether a
    market is live; status is advisory only.
    """
    _market(session, "ACTIVE", 1.0, status="active")
    post = _post(session, 1.0)

    assert [c.ticker for c in find_candidates(session, post, max_distance=2.0)] == ["ACTIVE"]
