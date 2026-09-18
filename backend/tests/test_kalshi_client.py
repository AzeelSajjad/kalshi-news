from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest
import respx

from app.clients.kalshi import BASE_URL, KalshiClient


@respx.mock
def test_fetch_all_markets_follows_pagination():
    page1 = {"markets": [{
        "ticker": "FED-26SEP", "event_ticker": "FED", "title": "Fed cuts in September?",
        "rules_primary": "Resolves YES if lowered.", "category": "Economics",
        "status": "active", "close_time": "2026-09-30T20:00:00Z",
        "yes_bid": 71, "yes_ask": 73, "volume": 5100000,
    }], "cursor": "next123"}
    page2 = {"markets": [{
        "ticker": "GOVSHUT-26OCT", "event_ticker": "GOVSHUT", "title": "Shutdown before Oct 15?",
        "rules_primary": "Resolves YES on a lapse.", "category": "Politics",
        "status": "active", "close_time": "2026-10-15T20:00:00Z",
        "yes_bid": 63, "yes_ask": 65, "volume": 2400000,
    }], "cursor": ""}

    route = respx.get(f"{BASE_URL}/markets")
    route.side_effect = [httpx.Response(200, json=page1), httpx.Response(200, json=page2)]

    markets = KalshiClient().fetch_all_markets()

    assert [m.ticker for m in markets] == ["FED-26SEP", "GOVSHUT-26OCT"]
    assert markets[0].yes_price == 72          # midpoint of bid/ask
    assert markets[0].close_time == datetime(2026, 9, 30, 20, 0, tzinfo=UTC)
    assert route.call_count == 2


@respx.mock
def test_fetch_all_markets_sends_no_auth_headers():
    respx.get(f"{BASE_URL}/markets").mock(
        return_value=httpx.Response(200, json={"markets": [], "cursor": ""}))

    KalshiClient().fetch_all_markets()

    sent = respx.calls[0].request.headers
    assert "KALSHI-ACCESS-KEY" not in sent
    assert "authorization" not in {k.lower() for k in sent}


@respx.mock
def test_fetch_candlesticks_returns_timestamp_price_pairs():
    respx.get(url__regex=rf"{BASE_URL}/series/.*/markets/FED-26SEP/candlesticks").mock(
        return_value=httpx.Response(200, json={"candlesticks": [
            {"end_period_ts": 1789600000, "price": {"close": 68}},
            {"end_period_ts": 1789603600, "price": {"close": 72}},
        ]}))

    points = KalshiClient().fetch_candlesticks(
        "FED-26SEP", datetime(2026, 9, 17, tzinfo=UTC),
        datetime(2026, 9, 18, tzinfo=UTC), series_ticker="FED")

    assert [p[1] for p in points] == [68, 72]
    assert points[0][0].tzinfo is UTC


@respx.mock
def test_a_404_is_attempted_once_not_retried():
    """A 404 (a delisted series, a market with no candlesticks) is a real
    answer, not a transient failure -- retrying it three times just costs
    two pointless backoff sleeps before failing anyway."""
    route = respx.get(f"{BASE_URL}/markets").mock(
        return_value=httpx.Response(404, json={"error": "not found"}))

    with pytest.raises(httpx.HTTPStatusError):
        KalshiClient().fetch_all_markets()

    assert route.call_count == 1


@respx.mock
@patch("time.sleep", return_value=None)
def test_a_500_is_retried_up_to_three_attempts(_sleep):
    route = respx.get(f"{BASE_URL}/markets").mock(
        return_value=httpx.Response(500, text="internal error"))

    with pytest.raises(httpx.HTTPStatusError):
        KalshiClient().fetch_all_markets()

    assert route.call_count == 3


@respx.mock
@patch("time.sleep", return_value=None)
def test_a_transport_error_is_retried_up_to_three_attempts(_sleep):
    route = respx.get(f"{BASE_URL}/markets").mock(side_effect=httpx.ConnectError("boom"))

    with pytest.raises(httpx.ConnectError):
        KalshiClient().fetch_all_markets()

    assert route.call_count == 3


# --- one-sided quotes ------------------------------------------------------
#
# The midpoint applies only when there is a genuine two-sided quote. With
# bid=0 and ask=97 -- common on a thin market the book has priced as a
# near-certain NO -- the old guard (`if bid or ask`) produced a confident-
# looking 48c on a market nobody is bidding on, and that number then went
# straight onto a card as fact.

def _one_market(**overrides):
    market = {
        "ticker": "THIN-1", "event_ticker": "THIN", "title": "Thin market?",
        "status": "active", "close_time": "2026-12-01T20:00:00Z",
        "last_price": 0, "volume": 3,
    }
    market.update(overrides)
    return {"markets": [market], "cursor": ""}


def _price_for(**overrides):
    with respx.mock:
        respx.get(f"{BASE_URL}/markets").mock(
            return_value=httpx.Response(200, json=_one_market(**overrides)))
        return KalshiClient().fetch_all_markets()[0].yes_price


def test_no_price_when_nobody_is_bidding():
    assert _price_for(yes_bid=0, yes_ask=97) is None


def test_no_price_when_nobody_is_offering():
    assert _price_for(yes_bid=45, yes_ask=0) is None


def test_no_price_when_a_side_is_absent_entirely():
    assert _price_for(yes_ask=97) is None
    assert _price_for(yes_bid=45) is None


def test_midpoint_survives_for_a_genuine_two_sided_quote():
    assert _price_for(yes_bid=45, yes_ask=47) == 46


def test_a_real_last_trade_still_wins_over_a_one_sided_quote():
    assert _price_for(yes_bid=0, yes_ask=97, last_price=93) == 93
