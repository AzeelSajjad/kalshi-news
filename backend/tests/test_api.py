from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Cluster, Market, Post, PostMarket, Source

NOW = datetime.now(UTC)


def _seed(session):
    source = Source(kind="rss", name="Politico", feed_url="u", category="Politics")
    session.add(source)
    session.flush()
    post = Post(source_id=source.id, external_id="p1", url="https://politico.com/a",
                title="Shutdown talks collapse", body="Leadership walked out.",
                author_name="Politico", category="Politics", published_at=NOW)
    session.add(post)
    session.add(Market(ticker="GOVSHUT-26OCT", title="Shutdown before Oct 15?",
                        rules_summary="Resolves YES on a lapse.", category="Politics",
                        status="open", close_time=NOW + timedelta(days=28),
                        yes_price=64, volume=2400000, text_hash="h"))
    session.flush()
    session.add(PostMarket(post_id=post.id, ticker="GOVSHUT-26OCT", direction="YES",
                            confidence=0.86, rationale="No path to a deal remains.",
                            price_at_link=53, price_1h=64))
    session.commit()
    return post


@pytest.fixture
def job_token(monkeypatch):
    """Sets JOB_TOKEN='secret' for the test and guarantees the cached
    Settings object is cleared afterward -- via fixture teardown, which
    pytest always runs even if the test body raises -- so an assertion
    failure can't leave job_token='secret' cached for every later test in
    the session.
    """
    monkeypatch.setenv("JOB_TOKEN", "secret")
    from app.config import get_settings
    get_settings.cache_clear()
    try:
        yield "secret"
    finally:
        get_settings.cache_clear()


@pytest.fixture
def blank_job_token(monkeypatch):
    monkeypatch.setenv("JOB_TOKEN", "")
    from app.config import get_settings
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def test_feed_returns_posts_newest_first_with_their_markets(session):
    _seed(session)
    response = TestClient(app).get("/api/feed")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["title"] == "Shutdown talks collapse"
    assert item["author_name"] == "Politico"
    assert item["markets"][0]["ticker"] == "GOVSHUT-26OCT"
    assert item["markets"][0]["direction"] == "YES"
    assert item["markets"][0]["price_delta"] == 11      # 64 - 53


def test_feed_orders_posts_newest_first(session):
    source = Source(kind="rss", name="Politico", feed_url="u", category="Politics")
    session.add(source)
    session.flush()
    older = Post(source_id=source.id, external_id="older", url="https://politico.com/1",
                 title="Older", author_name="a", category="Politics",
                 published_at=NOW - timedelta(hours=1))
    newer = Post(source_id=source.id, external_id="newer", url="https://politico.com/2",
                 title="Newer", author_name="a", category="Politics", published_at=NOW)
    session.add_all([older, newer])
    session.commit()

    items = TestClient(app).get("/api/feed").json()["items"]

    assert [item["title"] for item in items] == ["Newer", "Older"]


def test_feed_orders_a_posts_markets_by_confidence_descending(session):
    post = _seed(session)
    session.add(Market(ticker="OTHER-MKT", title="Other market", status="open",
                        close_time=NOW + timedelta(days=10), yes_price=40,
                        volume=100, text_hash="h3"))
    session.flush()
    session.add(PostMarket(post_id=post.id, ticker="OTHER-MKT", direction="NO",
                            confidence=0.95, rationale="stronger signal"))
    session.commit()

    item = TestClient(app).get(f"/api/posts/{post.id}").json()

    assert [m["ticker"] for m in item["markets"]] == ["OTHER-MKT", "GOVSHUT-26OCT"]


def test_feed_reports_cluster_size_from_the_cluster(session):
    cluster = Cluster(post_count=4)
    session.add(cluster)
    session.flush()
    source = Source(kind="rss", name="Politico", feed_url="u", category="Politics")
    session.add(source)
    session.flush()
    post = Post(source_id=source.id, external_id="clustered", url="https://politico.com/3",
                title="Clustered story", author_name="a", category="Politics",
                published_at=NOW, cluster_id=cluster.id)
    session.add(post)
    session.commit()

    item = TestClient(app).get("/api/feed").json()["items"][0]

    assert item["cluster_size"] == 4


def test_feed_filters_by_category(session):
    _seed(session)
    client = TestClient(app)

    assert len(client.get("/api/feed?category=Politics").json()["items"]) == 1
    assert client.get("/api/feed?category=Sports").json()["items"] == []


def test_feed_rejects_limit_below_one(session):
    client = TestClient(app)

    assert client.get("/api/feed", params={"limit": 0}).status_code == 422
    assert client.get("/api/feed", params={"limit": -5}).status_code == 422


def test_feed_does_not_emit_next_cursor_on_an_exactly_full_last_page(session):
    source = Source(kind="rss", name="Politico", feed_url="u", category="Politics")
    session.add(source)
    session.flush()
    for i in range(2):
        session.add(Post(source_id=source.id, external_id=f"exact{i}",
                          url=f"https://politico.com/exact{i}", title=f"Exact {i}",
                          author_name="a", category="Politics",
                          published_at=NOW - timedelta(minutes=i)))
    session.commit()

    payload = TestClient(app).get("/api/feed", params={"limit": 2}).json()

    assert len(payload["items"]) == 2
    assert payload["next_cursor"] is None


def test_feed_cursor_pagination_handles_posts_sharing_a_timestamp(session):
    """Three posts share one published_at. A bare-timestamp cursor with
    strict '<' would drop the third post from every page, forever, and
    which post gets dropped would vary run to run. The keyset cursor
    (published_at, id) must page through all three exactly once."""
    source = Source(kind="rss", name="Politico", feed_url="u", category="Politics")
    session.add(source)
    session.flush()
    for i in range(3):
        session.add(Post(source_id=source.id, external_id=f"tied{i}",
                          url=f"https://politico.com/tied{i}", title=f"Tied {i}",
                          author_name="a", category="Politics", published_at=NOW))
    session.commit()

    client = TestClient(app)
    page1 = client.get("/api/feed", params={"limit": 2}).json()
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None

    page2 = client.get(
        "/api/feed", params={"limit": 2, "cursor": page1["next_cursor"]}
    ).json()
    assert len(page2["items"]) == 1
    assert page2["next_cursor"] is None

    seen_titles = {item["title"] for item in page1["items"]} | {
        item["title"] for item in page2["items"]
    }
    assert seen_titles == {"Tied 0", "Tied 1", "Tied 2"}


def test_feed_rejects_malformed_cursor_with_422_not_500(session):
    response = TestClient(app).get("/api/feed", params={"cursor": "not-a-real-cursor"})
    assert response.status_code == 422


def test_feed_rejects_naive_timezone_cursor(session):
    naive = "2026-09-17T12:00:00|1"  # no UTC offset
    response = TestClient(app).get("/api/feed", params={"cursor": naive})
    assert response.status_code == 422


def test_post_detail_includes_body_and_rationales(session):
    post = _seed(session)
    payload = TestClient(app).get(f"/api/posts/{post.id}").json()

    assert payload["body"] == "Leadership walked out."
    assert payload["url"] == "https://politico.com/a"
    assert payload["markets"][0]["rationale"] == "No path to a deal remains."
    assert payload["markets"][0]["kalshi_url"].startswith("https://kalshi.com/markets/")
    assert "utm_source" in payload["markets"][0]["kalshi_url"]


def test_unknown_post_returns_404(session):
    assert TestClient(app).get("/api/posts/999999").status_code == 404


def test_trending_returns_both_rankings(session):
    _seed(session)
    payload = TestClient(app).get("/api/trending").json()

    assert payload["by_volume"][0]["ticker"] == "GOVSHUT-26OCT"
    assert payload["most_covered"][0]["post_count"] == 1


def test_trending_rejects_limit_below_one(session):
    assert TestClient(app).get("/api/trending", params={"limit": 0}).status_code == 422


def test_most_covered_only_counts_links_from_the_last_24h(session):
    """The spec calls this "most covered today" -- a link recorded days ago
    must not keep inflating the count forever."""
    recent_post = _seed(session)  # GOVSHUT-26OCT link, created_at defaults to now

    session.add(Market(ticker="OLD-MKT", title="Old story", status="open",
                        close_time=NOW + timedelta(days=10), yes_price=50,
                        volume=100, text_hash="h3"))
    session.flush()
    old_post = Post(source_id=recent_post.source_id, external_id="old1",
                     url="https://politico.com/old", title="Old story broke",
                     category="Politics", published_at=NOW - timedelta(hours=30))
    session.add(old_post)
    session.flush()
    session.add(PostMarket(post_id=old_post.id, ticker="OLD-MKT", direction="YES",
                            confidence=0.7, rationale="r", price_at_link=50,
                            created_at=NOW - timedelta(hours=25)))
    session.commit()

    payload = TestClient(app).get("/api/trending").json()

    tickers = [m["ticker"] for m in payload["most_covered"]]
    assert "GOVSHUT-26OCT" in tickers   # link from just now: included
    assert "OLD-MKT" not in tickers     # link from 25h ago: excluded


def test_trending_excludes_markets_past_close_time_even_if_status_still_open(session):
    """status goes stale (Kalshi stops returning settled markets from its open
    feed), so a market whose close_time is in the past must be excluded from
    trending even though its status row is still 'open'."""
    session.add(Market(ticker="STALE-MKT", title="Already closed", status="open",
                        close_time=NOW - timedelta(days=1), yes_price=99,
                        volume=9999999, text_hash="h2"))
    session.commit()

    payload = TestClient(app).get("/api/trending").json()

    tickers = [m["ticker"] for m in payload["by_volume"]]
    assert "STALE-MKT" not in tickers


def test_trending_kalshi_urls_carry_utm_parameters(session):
    _seed(session)
    payload = TestClient(app).get("/api/trending").json()

    assert "utm_source" in payload["by_volume"][0]["kalshi_url"]


def test_job_endpoint_requires_the_token(session):
    client = TestClient(app)

    assert client.post("/api/jobs/ingest").status_code == 401
    assert client.post("/api/jobs/ingest", headers={"X-Job-Token": "wrong"}).status_code == 401


def test_job_endpoint_rejects_everything_when_token_is_blank(session, blank_job_token):
    """A blank configured job_token must fail closed: reject every request,
    including one that (accidentally or not) sends a blank header too."""
    client = TestClient(app)
    assert client.post("/api/jobs/ingest").status_code == 401
    assert client.post("/api/jobs/ingest", headers={"X-Job-Token": ""}).status_code == 401


def test_job_endpoint_runs_the_named_job(session, job_token):
    with patch("app.api.run_ingest", return_value=7) as job:
        response = TestClient(app).post(
            "/api/jobs/ingest", headers={"X-Job-Token": job_token})

    assert response.status_code == 200
    assert response.json() == {"job": "ingest", "items_processed": 7}
    job.assert_called_once()


def test_unknown_job_name_returns_404(session, job_token):
    response = TestClient(app).post("/api/jobs/nope", headers={"X-Job-Token": job_token})
    assert response.status_code == 404


def test_job_endpoint_returns_500_not_a_traceback_when_the_job_raises(session, job_token):
    with patch("app.api.sync_markets", side_effect=RuntimeError("kalshi is down")):
        response = TestClient(app).post(
            "/api/jobs/sync_markets", headers={"X-Job-Token": job_token})

    assert response.status_code == 500
    assert "sync_markets" in response.json()["detail"]
    assert "kalshi is down" not in response.json()["detail"]
    assert response.json()["detail"] == "job sync_markets failed: RuntimeError"


def test_feed_does_not_n_plus_1_per_post(session):
    """A page of many posts must load their markets/clusters/sources in a
    bounded number of queries, not one query per post."""
    source = Source(kind="rss", name="Politico", feed_url="u", category="Politics")
    session.add(source)
    session.flush()
    for i in range(10):
        session.add(Post(source_id=source.id, external_id=f"p{i}",
                          url=f"https://politico.com/{i}", title=f"Story {i}",
                          body="body", author_name="Politico", category="Politics",
                          published_at=NOW - timedelta(minutes=i)))
    session.commit()

    from app.db import engine

    query_count = 0

    from sqlalchemy import event

    def _count(*args, **kwargs):
        nonlocal query_count
        query_count += 1

    event.listen(engine, "before_cursor_execute", _count)
    try:
        response = TestClient(app).get("/api/feed?limit=10")
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert response.status_code == 200
    assert len(response.json()["items"]) == 10
    # Bounded regardless of page size: posts (+1 lookahead row), source
    # eager-load, links+markets, clusters -- a handful of queries, never one
    # per post.
    assert query_count <= 6, f"expected a bounded query count, got {query_count}"
