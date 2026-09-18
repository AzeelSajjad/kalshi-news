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
