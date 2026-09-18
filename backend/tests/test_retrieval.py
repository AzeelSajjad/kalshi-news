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


def test_excludes_settled_and_expired_markets(session):
    _market(session, "SETTLED", 1.0, status="settled")
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
