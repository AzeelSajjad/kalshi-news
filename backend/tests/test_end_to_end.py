"""One test that crosses every stage boundary, with no network.

Every other test in this suite starts from hand-constructed ORM rows, so a
producer and a consumer can disagree about a value while both halves stay
green -- which is exactly what happened: sync_markets wrote
markets.status = "active" (what Kalshi actually returns) while the linker
and the API both filtered on status == "open", so nothing downstream of a
real sync could ever match. This composes the real jobs --
sync_markets -> run_ingest -> run_link -> GET /api/feed -- against a
recorded-shape Kalshi payload so that class of gap fails here.

The only stubs are the external boundaries: the Kalshi HTTP response
(respx), the ingestor's fetch, the embedding API, and the Anthropic call.
Every database write and read in between is the production code path.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import httpx
import respx
from fastapi.testclient import TestClient

from app.clients.kalshi import BASE_URL
from app.ingest.base import RawPost
from app.jobs.ingest import run_ingest
from app.jobs.link import run_link
from app.jobs.sync_markets import sync_markets
from app.linker.verifier import VerificationResult, VerifiedLink
from app.main import app
from app.models import Source

NOW = datetime.now(UTC)
CLOSE_TIME = NOW + timedelta(days=28)

# Field names and shape taken from a recorded GET /trade-api/v2/markets
# response. status is "active": that is the literal value Kalshi returns for
# a live market, and running the real sync job over it is the whole point of
# this test.
MARKETS_PAYLOAD = {
    "markets": [
        {
            "ticker": "GOVSHUT-26OCT15",
            "event_ticker": "GOVSHUT-26OCT",
            "series_ticker": "GOVSHUT",
            "market_type": "binary",
            "title": "Government shutdown before Oct 15, 2026?",
            "subtitle": "",
            "rules_primary": "This market resolves YES if a lapse in federal "
                             "appropriations begins before Oct 15, 2026.",
            "rules_secondary": "",
            "category": "Politics",
            "status": "active",
            "open_time": (NOW - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "close_time": CLOSE_TIME.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expiration_time": CLOSE_TIME.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "yes_bid": 63,
            "yes_ask": 65,
            "no_bid": 35,
            "no_ask": 37,
            "last_price": 64,
            "previous_yes_bid": 60,
            "volume": 2400000,
            "volume_24h": 180000,
            "open_interest": 910000,
            "liquidity": 120000,
            "can_close_early": True,
            "result": "",
        }
    ],
    "cursor": "",
}

VECTOR = [1.0] + [0.0] * 1535

ARTICLE = RawPost(
    external_id="politico-guid-1",
    url="https://www.politico.com/news/2026/09/17/shutdown-talks-collapse",
    title="Shutdown talks collapse as leadership walks out",
    body="Negotiators left the room with no scheduled path back before the deadline.",
    author_name="Politico",
    published_at=NOW - timedelta(minutes=5),
)


def _stub_verify(post, candidates, client=None):
    """Stands in for the Anthropic call, but only ever affirms markets that
    retrieval actually handed it. A stub that returned a fixed link
    regardless of `candidates` would paper over a retrieval stage that
    returns nothing -- which is precisely the bug this test exists to catch.
    """
    return VerificationResult(
        [
            VerifiedLink(
                ticker=candidate.ticker,
                related=True,
                direction="YES",
                confidence=0.86,
                rationale="Leadership walking out removes the last scheduled "
                          "path to a deal before the deadline.",
            )
            for candidate in candidates
        ],
        1200,
        300,
    )


@respx.mock
def test_recorded_kalshi_payload_flows_through_to_a_tagged_feed_item(session):
    session.add(Source(kind="rss", name="Politico",
                       feed_url="https://www.politico.com/rss/politics.xml",
                       category="Politics"))
    session.commit()

    # --- stage 1: Kalshi sync, over the real client and the real parser ---
    respx.get(f"{BASE_URL}/markets").mock(
        return_value=httpx.Response(200, json=MARKETS_PAYLOAD))
    with patch("app.jobs.sync_markets.embed_texts", return_value=[VECTOR]):
        assert sync_markets(session) == 1

    # --- stage 2: ingest ---
    ingestor = MagicMock()
    ingestor.kind = "rss"
    ingestor.fetch.return_value = [ARTICLE]
    assert run_ingest(session, ingestors={"rss": ingestor}) == 1

    # --- stage 3: link ---
    with patch("app.jobs.link.embed_texts", return_value=[VECTOR]), \
         patch("app.jobs.link.verify_candidates", side_effect=_stub_verify) as verify:
        assert run_link(session) == 1

    verify.assert_called_once()
    candidates = verify.call_args.args[1]
    assert [c.ticker for c in candidates] == ["GOVSHUT-26OCT15"], (
        "retrieval handed the verifier no candidates -- the synced market was "
        "filtered out before it ever reached the LLM"
    )

    # --- stage 4: the read API a recruiter actually loads ---
    client = TestClient(app)
    item = client.get("/api/feed").json()["items"][0]
    assert item["title"] == ARTICLE.title
    assert item["source_kind"] == "rss"
    assert [m["ticker"] for m in item["markets"]] == ["GOVSHUT-26OCT15"]
    assert item["markets"][0]["direction"] == "YES"
    assert item["markets"][0]["yes_price"] == 64          # midpoint of 63/65

    detail = client.get(f"/api/posts/{item['id']}").json()
    assert detail["body"] == ARTICLE.body
    assert detail["markets"][0]["rationale"].startswith("Leadership walking out")

    trending = client.get("/api/trending").json()
    assert [m["ticker"] for m in trending["by_volume"]] == ["GOVSHUT-26OCT15"]
    assert [m["ticker"] for m in trending["most_covered"]] == ["GOVSHUT-26OCT15"]
    assert trending["most_covered"][0]["post_count"] == 1
