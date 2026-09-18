from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import Market, Post, PostMarket, Source

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


def test_feed_filters_by_category(session):
    _seed(session)
    client = TestClient(app)

    assert len(client.get("/api/feed?category=Politics").json()["items"]) == 1
    assert client.get("/api/feed?category=Sports").json()["items"] == []


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


def test_job_endpoint_rejects_everything_when_token_is_blank(session, monkeypatch):
    """A blank configured job_token must fail closed: reject every request,
    including one that (accidentally or not) sends a blank header too."""
    monkeypatch.setenv("JOB_TOKEN", "")
    from app.config import get_settings
    get_settings.cache_clear()

    client = TestClient(app)
    assert client.post("/api/jobs/ingest").status_code == 401
    assert client.post("/api/jobs/ingest", headers={"X-Job-Token": ""}).status_code == 401
    get_settings.cache_clear()


def test_job_endpoint_runs_the_named_job(session, monkeypatch):
    monkeypatch.setenv("JOB_TOKEN", "secret")
    from app.config import get_settings
    get_settings.cache_clear()

    with patch("app.api.run_ingest", return_value=7) as job:
        response = TestClient(app).post("/api/jobs/ingest", headers={"X-Job-Token": "secret"})

    assert response.status_code == 200
    assert response.json() == {"job": "ingest", "items_processed": 7}
    job.assert_called_once()
    get_settings.cache_clear()


def test_unknown_job_name_returns_404(session, monkeypatch):
    monkeypatch.setenv("JOB_TOKEN", "secret")
    from app.config import get_settings
    get_settings.cache_clear()

    response = TestClient(app).post("/api/jobs/nope", headers={"X-Job-Token": "secret"})
    assert response.status_code == 404
    get_settings.cache_clear()


def test_job_endpoint_returns_500_not_a_traceback_when_the_job_raises(session, monkeypatch):
    monkeypatch.setenv("JOB_TOKEN", "secret")
    from app.config import get_settings
    get_settings.cache_clear()

    with patch("app.api.sync_markets", side_effect=RuntimeError("kalshi is down")):
        response = TestClient(app).post(
            "/api/jobs/sync_markets", headers={"X-Job-Token": "secret"})

    assert response.status_code == 500
    assert "sync_markets" in response.json()["detail"]
    get_settings.cache_clear()


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
    # Bounded regardless of page size: posts, source eager-load, links+markets,
    # clusters -- a handful of queries, never one per post.
    assert query_count <= 6, f"expected a bounded query count, got {query_count}"
