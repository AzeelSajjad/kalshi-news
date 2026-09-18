import json
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
