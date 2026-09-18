from datetime import UTC, datetime

from app.clients.kalshi import KalshiMarket
from app.market_text import compose_market_text, text_hash

MARKET = KalshiMarket(
    ticker="FED-26SEP-T4.50", event_ticker="FED", series_ticker="FED",
    title="Fed target rate above 4.50% in September?",
    rules_summary="Resolves YES if the upper bound exceeds 4.50%.",
    category="Economics", status="active",
    close_time=datetime(2026, 9, 30, tzinfo=UTC), yes_price=72, volume=1,
)


def test_composed_text_is_human_readable_not_just_the_ticker():
    text = compose_market_text(MARKET)
    assert "Fed target rate above 4.50% in September?" in text
    assert "Resolves YES if the upper bound exceeds 4.50%." in text
    assert "Economics" in text
    assert "2026-09-30" in text
    assert "FED-26SEP-T4.50" not in text


def test_text_hash_is_stable_and_changes_with_content():
    assert text_hash("abc") == text_hash("abc")
    assert len(text_hash("abc")) == 64
    assert text_hash("abc") != text_hash("abd")
