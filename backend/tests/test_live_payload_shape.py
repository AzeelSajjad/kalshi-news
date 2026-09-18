"""Pins a real Kalshi API response so a retrieval/status regression is caught by recorded
data, not by a hand-built fixture that re-encodes the same assumption this task exists to
eliminate.

Provenance
----------
Captured 2026-09-18 via::

    GET https://external-api.kalshi.com/trade-api/v2/markets?limit=3&status=open

`fixtures/kalshi_markets_live.json` is that real, unmodified response, except for two
deliberate edits made below/at capture time -- neither touches `status`, which is left
exactly as Kalshi returned it (`"active"`, not `"open"`; see task-1-report.md in
.superpowers/sdd/2026-09-18-frontend-and-deploy/ for why that distinction is the point of
this file):

1. The top-level `cursor` field was blanked to `""` at capture time. The real response had a
   non-empty Kalshi pagination token (there are more than 3 open markets). The `respx.mock`
   below always replays the same response body regardless of the request's `cursor` param, so
   replaying the real token verbatim sends `KalshiClient.fetch_all_markets`'s `while True`
   loop into an infinite spin against a static mock -- confirmed by hand (2.5+ minutes pinned
   at ~95% CPU before the process was killed). This is a test-harness workaround for a static
   mock, not a claim that the client's pagination loop is fine as written; the unbounded loop
   itself is tracked separately as issue #43.
2. Each market's `close_time` is rewritten below, at import time, to `now + 30 days`. The raw
   capture's close_time values are fixed calendar dates a few days out from 2026-09-18.
   `find_candidates` filters on `close_time > now()`, so replaying those fixed dates verbatim
   would make `test_synced_markets_are_retrievable_regardless_of_status_value` rot into a
   false "retrieval is broken" failure within about a week of merge -- indistinguishable, to
   whoever sees it, from a real status-coupling regression. Shifting relative to `now()` at
   load time keeps the fixture evergreen without touching any other field (status, ticker,
   title, etc. are untouched).
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
import respx

from app.clients.kalshi import BASE_URL, KalshiClient
from app.jobs.sync_markets import sync_markets
from app.linker.retrieval import find_candidates
from app.models import Market, Post, Source

# Imported at module level, not inside the test body: pytest imports every
# test module during collection, before any fixture runs. The session-scoped
# `engine` fixture in conftest.py builds its tables from `Base.metadata`,
# which is only populated once `app.models` has been imported somewhere.
# Every other test module imports it at the top for the same reason -- a
# local import here would leave `Base.metadata` empty when this file is run
# on its own (`pytest tests/test_live_payload_shape.py`), even though the
# same file passes as part of the full suite where another module's
# top-level import happens to run first.
LIVE = json.loads((Path(__file__).parent / "fixtures" / "kalshi_markets_live.json").read_text())

# See module docstring, edit 2: shift every market's close_time to a fixed offset from
# *now*, evaluated when this module loads, so the fixture never rots into a false
# "retrieval is broken" failure as real calendar time passes. status and every other
# recorded field are left untouched.
_FUTURE_CLOSE_TIME = (datetime.now(UTC) + timedelta(days=30)).isoformat()
for _market in LIVE["markets"]:
    _market["close_time"] = _FUTURE_CLOSE_TIME


@respx.mock
def test_client_parses_a_real_recorded_payload():
    respx.get(f"{BASE_URL}/markets").mock(return_value=httpx.Response(200, json=LIVE))

    markets = KalshiClient().fetch_all_markets()

    assert markets, "recorded payload produced no markets"
    first = markets[0]
    assert first.ticker
    assert first.title
    assert first.close_time is not None and first.close_time.tzinfo is not None


@respx.mock
def test_synced_markets_are_retrievable_regardless_of_status_value(session):
    """The status field is advisory; retrieval must not depend on its value."""
    respx.get(f"{BASE_URL}/markets").mock(return_value=httpx.Response(200, json=LIVE))
    with patch("app.jobs.sync_markets.embed_texts") as embed:
        embed.side_effect = lambda texts: [[0.1] * 1536 for _ in texts]
        sync_markets(session)

    stored = session.query(Market).first()
    assert stored is not None
    source = Source(kind="rss", name="R", feed_url="u", category="Economics")
    session.add(source)
    session.flush()
    post = Post(source_id=source.id, external_id="p", url="u", title="t",
                published_at=stored.close_time, embedding=[0.1] * 1536)
    session.add(post)
    session.commit()

    assert find_candidates(session, post, max_distance=2.0), (
        "a freshly synced market was not retrievable — retrieval is coupled to status again"
    )


def test_real_payload_yields_usable_prices_and_volume():
    """The live API uses *_dollars and *_fp names; parsing must produce cents and ints."""
    import httpx
    import respx

    from app.clients.kalshi import BASE_URL, KalshiClient

    payload = {"markets": [{
        "ticker": "TEST-1", "event_ticker": "TEST", "title": "A market?",
        "rules_primary": "Resolves YES.", "status": "active",
        "close_time": "2026-12-01T20:00:00Z",
        "yes_bid_dollars": "0.6300", "yes_ask_dollars": "0.6500",
        "last_price_dollars": "0.6400", "volume_fp": "2400000.00",
    }], "cursor": ""}

    with respx.mock:
        respx.get(f"{BASE_URL}/markets").mock(return_value=httpx.Response(200, json=payload))
        market = KalshiClient().fetch_all_markets()[0]

    assert market.yes_price == 64, "last_price_dollars should win and convert to cents"
    assert market.volume == 2400000


def test_untraded_market_reports_no_price_rather_than_a_fake_midpoint():
    import httpx
    import respx

    from app.clients.kalshi import BASE_URL, KalshiClient

    payload = {"markets": [{
        "ticker": "TEST-2", "event_ticker": "TEST", "title": "Untraded?",
        "status": "active", "close_time": "2026-12-01T20:00:00Z",
        "yes_bid_dollars": "0.0000", "yes_ask_dollars": "0.0000",
        "last_price_dollars": "0.0000", "volume_fp": "0.00",
    }], "cursor": ""}

    with respx.mock:
        respx.get(f"{BASE_URL}/markets").mock(return_value=httpx.Response(200, json=payload))
        market = KalshiClient().fetch_all_markets()[0]

    assert market.yes_price is None
    assert market.volume == 0


def test_midpoint_is_used_when_there_is_a_quote_but_no_last_trade():
    import httpx
    import respx

    from app.clients.kalshi import BASE_URL, KalshiClient

    payload = {"markets": [{
        "ticker": "TEST-3", "event_ticker": "TEST", "title": "Quoted?",
        "status": "active", "close_time": "2026-12-01T20:00:00Z",
        "yes_bid_dollars": "0.4000", "yes_ask_dollars": "0.4400",
        "last_price_dollars": "0.0000", "volume_fp": "10.00",
    }], "cursor": ""}

    with respx.mock:
        respx.get(f"{BASE_URL}/markets").mock(return_value=httpx.Response(200, json=payload))
        market = KalshiClient().fetch_all_markets()[0]

    assert market.yes_price == 42


def test_a_malformed_price_does_not_abort_the_sync():
    import httpx
    import respx

    from app.clients.kalshi import BASE_URL, KalshiClient

    payload = {"markets": [{
        "ticker": "TEST-4", "event_ticker": "TEST", "title": "Broken?",
        "status": "active", "close_time": "2026-12-01T20:00:00Z",
        "yes_bid_dollars": "not-a-number", "volume_fp": None,
    }], "cursor": ""}

    with respx.mock:
        respx.get(f"{BASE_URL}/markets").mock(return_value=httpx.Response(200, json=payload))
        market = KalshiClient().fetch_all_markets()[0]

    assert market.ticker == "TEST-4"
    assert market.yes_price is None
    assert market.volume is None


def test_pagination_stops_when_the_cursor_repeats():
    """A static cursor previously spun `while True` forever at 95% CPU."""
    import httpx
    import respx

    from app.clients.kalshi import BASE_URL, KalshiClient

    page = {"markets": [{"ticker": "T", "title": "t", "status": "active"}], "cursor": "same"}

    with respx.mock:
        route = respx.get(f"{BASE_URL}/markets").mock(
            return_value=httpx.Response(200, json=page))
        markets = KalshiClient().fetch_all_markets()

    assert route.call_count == 2, "should send the cursor once, see it repeat, and stop"
    assert len(markets) == 2
