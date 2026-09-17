from datetime import datetime, timezone
from app.models import Source, Post, Market, PostMarket


def test_post_market_link_round_trips(session):
    source = Source(kind="rss", name="Reuters", feed_url="https://r.com/rss", category="Economics")
    session.add(source)
    session.flush()

    post = Post(
        source_id=source.id,
        external_id="abc123",
        url="https://r.com/a",
        author_name="Reuters",
        title="Powell signals cut",
        body="Officials see room to ease.",
        published_at=datetime(2026, 9, 17, tzinfo=timezone.utc),
        embedding=[0.1] * 1536,
    )
    market = Market(
        ticker="FED-26SEP",
        event_ticker="FED",
        title="Fed cuts rates in September?",
        rules_summary="Resolves YES if the target rate is lowered.",
        category="Economics",
        status="open",
        close_time=datetime(2026, 9, 30, tzinfo=timezone.utc),
        yes_price=72,
        volume=5100000,
        text_hash="deadbeef",
        embedding=[0.2] * 1536,
    )
    session.add_all([post, market])
    session.flush()

    session.add(PostMarket(
        post_id=post.id, ticker=market.ticker, direction="YES",
        confidence=0.86, rationale="Powell signaled a cut.", price_at_link=72,
    ))
    session.commit()

    link = session.query(PostMarket).one()
    assert link.direction == "YES"
    assert link.post.title == "Powell signals cut"
    assert link.market.ticker == "FED-26SEP"


def test_post_external_id_is_unique_per_source(session):
    import pytest
    from sqlalchemy.exc import IntegrityError

    source = Source(kind="rss", name="AP", feed_url="https://ap.com/rss", category="World")
    session.add(source)
    session.flush()
    for _ in range(2):
        session.add(Post(source_id=source.id, external_id="dup", url="https://ap.com/x",
                         title="t", published_at=datetime.now(timezone.utc)))
    with pytest.raises(IntegrityError):
        session.commit()
