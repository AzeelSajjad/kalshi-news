from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import httpx

from app.clients.kalshi import KalshiMarket
from app.jobs.sync_markets import sync_markets
from app.models import JobRun, Market

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


def test_sync_dedupes_duplicate_ticker_within_one_fetch(session):
    """Pagination boundary overlap could return the same ticker twice in one fetch.

    Without deduping against markets created earlier in the same loop, the
    second occurrence would try to INSERT a second row with the same primary
    key, raising IntegrityError and killing the whole sync run.
    """
    with patch("app.jobs.sync_markets.embed_texts", return_value=[[0.3] * 1536, [0.3] * 1536]):
        count = sync_markets(session, client=_client([M, M]))

    assert count == 2
    assert session.query(Market).count() == 1


def test_job_run_is_recorded_on_success(session):
    with patch("app.jobs.sync_markets.embed_texts", return_value=[[0.3] * 1536]):
        sync_markets(session, client=_client([M]))

    run = session.query(JobRun).filter_by(job="sync_markets").one()
    assert run.status == "ok"
    assert run.items_processed == 1
    assert run.finished_at is not None


def test_a_kalshi_outage_is_recorded_not_raised(session):
    """Previously the only job with no JobRun: a Kalshi outage aborted the
    whole sync and left nothing in job_runs to look at."""
    client = MagicMock()
    client.fetch_all_markets.side_effect = httpx.ConnectError("kalshi is down")

    assert sync_markets(session, client=client) == 0

    run = session.query(JobRun).filter_by(job="sync_markets").one()
    assert run.status == "error"
    assert "kalshi is down" in run.error
    assert run.finished_at is not None


def test_one_bad_row_costs_its_chunk_not_the_whole_catalog(session):
    """title=None violates the NOT NULL constraint on markets.title, so that
    chunk fails at commit. With a single unchunked upsert the entire catalog
    would be rolled back; chunked, the good markets still land."""
    bad = KalshiMarket(**{**M.__dict__, "ticker": "BAD-26SEP", "title": None})
    other = KalshiMarket(**{**M.__dict__, "ticker": "GOOD-26SEP"})

    with patch("app.jobs.sync_markets.CHUNK_SIZE", 1), \
         patch("app.jobs.sync_markets.embed_texts", return_value=[[0.3] * 1536]):
        synced = sync_markets(session, client=_client([M, bad, other]))

    assert synced == 2
    assert {m.ticker for m in session.query(Market).all()} == {"FED-26SEP", "GOOD-26SEP"}
    run = session.query(JobRun).filter_by(job="sync_markets").one()
    assert run.status == "error"
    assert "chunk" in run.error


def test_a_job_constructed_client_is_closed_after_the_run(session):
    mock_client = MagicMock()
    mock_client.fetch_all_markets.return_value = []
    with patch("app.jobs.sync_markets.KalshiClient", return_value=mock_client):
        sync_markets(session)

    mock_client.close.assert_called_once()


def test_an_injected_client_is_not_closed_by_the_job(session):
    client = _client([])

    sync_markets(session, client=client)

    client.close.assert_not_called()
