from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from app.clients.kalshi import KalshiMarket
from app.jobs.sync_markets import sync_markets
from app.models import Market

M = KalshiMarket(
    ticker="FED-26SEP", event_ticker="FED", series_ticker="FED",
    title="Fed cuts in September?", rules_summary="Resolves YES if lowered.",
    category="Economics", status="active",
    close_time=datetime(2026, 9, 30, tzinfo=UTC), yes_price=72, volume=5100000,
)


def _client(markets):
    client = MagicMock()
    client.fetch_all_markets.return_value = markets
    return client


def test_sync_inserts_markets_and_embeds_them(session):
    with patch("app.jobs.sync_markets.embed_texts", return_value=[[0.3] * 1536]) as embed:
        count = sync_markets(session, client=_client([M]))

    assert count == 1
    market = session.query(Market).one()
    assert market.ticker == "FED-26SEP"
    assert market.yes_price == 72
    assert market.embedding is not None
    assert embed.call_count == 1


def test_resync_with_unchanged_text_does_not_re_embed(session):
    with patch("app.jobs.sync_markets.embed_texts", return_value=[[0.3] * 1536]):
        sync_markets(session, client=_client([M]))

    updated = KalshiMarket(**{**M.__dict__, "yes_price": 80})
    with patch("app.jobs.sync_markets.embed_texts", return_value=[]) as embed:
        sync_markets(session, client=_client([updated]))

    assert embed.call_args.args[0] == []          # nothing re-embedded
    assert session.query(Market).one().yes_price == 80   # price still refreshed


def test_sync_is_idempotent(session):
    with patch("app.jobs.sync_markets.embed_texts", return_value=[[0.3] * 1536]):
        sync_markets(session, client=_client([M]))
        sync_markets(session, client=_client([M]))

    assert session.query(Market).count() == 1
