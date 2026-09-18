from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import httpx

from app.ingest.base import RawPost
from app.jobs.ingest import run_ingest
from app.models import JobRun, Post, Source

POST = RawPost(external_id="guid-1", url="https://r.com/a", title="Powell signals cut",
               body="Officials see room to ease.", author_name="Reuters",
               published_at=datetime(2026, 9, 17, 14, 2, tzinfo=UTC))

TWEET_POST = RawPost(
    external_id="guid-2", url="https://r.com/b", title="Fed watchers weigh in",
    body="Analysts pointed to https://twitter.com/foo/status/1839000000000000005 as evidence.",
    author_name="Reuters",
    published_at=datetime(2026, 9, 17, 14, 5, tzinfo=UTC),
)


def _ingestor(posts, kind="rss"):
    ingestor = MagicMock()
    ingestor.kind = kind
    ingestor.fetch.return_value = posts
    return ingestor


def test_ingest_stores_new_posts(session):
    session.add(Source(kind="rss", name="Reuters", feed_url="https://r.com/rss",
                       category="Economics"))
    session.commit()

    count = run_ingest(session, ingestors={"rss": _ingestor([POST])})

    assert count == 1
    post = session.query(Post).one()
    assert post.title == "Powell signals cut"
    assert post.category == "Economics"


def test_reingesting_the_same_item_is_a_no_op(session):
    session.add(Source(kind="rss", name="Reuters", feed_url="https://r.com/rss",
                       category="Economics"))
    session.commit()

    run_ingest(session, ingestors={"rss": _ingestor([POST])})
    second = run_ingest(session, ingestors={"rss": _ingestor([POST])})

    assert second == 0
    assert session.query(Post).count() == 1


def test_one_failing_source_does_not_stop_the_others(session):
    session.add_all([
        Source(kind="rss", name="Broken", feed_url="https://broken.com/rss", category="World"),
        Source(kind="rss", name="Reuters", feed_url="https://r.com/rss", category="Economics"),
    ])
    session.commit()

    ingestor = MagicMock()
    ingestor.kind = "rss"
    ingestor.fetch.side_effect = [httpx.ConnectError("boom"), [POST]]

    count = run_ingest(session, ingestors={"rss": ingestor})

    assert count == 1
    assert session.query(Post).count() == 1


def test_disabled_sources_are_skipped(session):
    session.add(Source(kind="rss", name="Off", feed_url="https://off.com/rss",
                       category="World", enabled=False))
    session.commit()

    ingestor = _ingestor([POST])
    assert run_ingest(session, ingestors={"rss": ingestor}) == 0
    ingestor.fetch.assert_not_called()


def test_job_run_is_recorded(session):
    session.add(Source(kind="rss", name="Reuters", feed_url="https://r.com/rss",
                       category="Economics"))
    session.commit()

    run_ingest(session, ingestors={"rss": _ingestor([POST])})

    run = session.query(JobRun).filter_by(job="ingest").one()
    assert run.status == "ok"
    assert run.items_processed == 1
    assert run.finished_at is not None


def test_discovered_tweet_ids_are_hydrated_by_the_x_source(session):
    session.add_all([
        Source(kind="rss", name="Reuters", feed_url="https://r.com/rss", category="Economics"),
        Source(kind="x", name="X Feed", handle="feed", category="Economics"),
    ])
    session.commit()

    rss_ingestor = _ingestor([TWEET_POST], kind="rss")
    x_ingestor = _ingestor([], kind="x")

    run_ingest(session, ingestors={"rss": rss_ingestor, "x": x_ingestor})

    x_ingestor.fetch.assert_called_once()
    called_source = x_ingestor.fetch.call_args.args[0]
    assert called_source.pending_tweet_ids == ["1839000000000000005"]


def test_already_stored_tweet_id_is_not_rehydrated(session):
    rss_source = Source(kind="rss", name="Reuters", feed_url="https://r.com/rss",
                        category="Economics")
    x_source = Source(kind="x", name="X Feed", handle="feed", category="Economics")
    session.add_all([rss_source, x_source])
    session.commit()

    session.add(Post(
        source_id=x_source.id, external_id="1839000000000000005",
        url="https://x.com/foo/status/1839000000000000005", title="already there",
        published_at=datetime(2026, 9, 17, 12, 0, tzinfo=UTC),
    ))
    session.commit()

    rss_ingestor = _ingestor([TWEET_POST], kind="rss")
    x_ingestor = _ingestor([], kind="x")

    run_ingest(session, ingestors={"rss": rss_ingestor, "x": x_ingestor})

    called_source = x_ingestor.fetch.call_args.args[0]
    assert called_source.pending_tweet_ids == []


def test_in_batch_duplicate_external_id_is_stored_once(session):
    session.add(Source(kind="rss", name="Reuters", feed_url="https://r.com/rss",
                       category="Economics"))
    session.commit()

    duplicate = RawPost(external_id="guid-1", url="https://r.com/a-dup", title="Duplicate guid",
                        body="Same guid, different text.", author_name="Reuters",
                        published_at=datetime(2026, 9, 17, 14, 3, tzinfo=UTC))

    count = run_ingest(session, ingestors={"rss": _ingestor([POST, duplicate])})

    assert count == 1
    assert session.query(Post).count() == 1


def test_a_store_phase_failure_is_isolated_and_leaves_the_session_usable(session):
    session.add_all([
        Source(kind="rss", name="Broken", feed_url="https://broken.com/rss", category="World"),
        Source(kind="rss", name="Reuters", feed_url="https://r.com/rss", category="Economics"),
    ])
    session.commit()

    # title=None violates the NOT NULL constraint on posts.title, so this
    # source's store phase fails at commit -- after its fetch already
    # succeeded, unlike the ConnectError case above.
    broken_post = RawPost(external_id="guid-x", url="https://broken.com/a", title=None,
                          body="oops", author_name="Broken",
                          published_at=datetime(2026, 9, 17, 14, 2, tzinfo=UTC))

    ingestor = MagicMock()
    ingestor.kind = "rss"
    ingestor.fetch.side_effect = [[broken_post], [POST]]

    count = run_ingest(session, ingestors={"rss": ingestor})

    assert count == 1
    assert session.query(Post).count() == 1
    assert session.query(Post).one().title == "Powell signals cut"


def test_two_x_sources_do_not_double_hydrate_the_same_tweet(session):
    session.add_all([
        Source(kind="rss", name="Reuters", feed_url="https://r.com/rss", category="Economics"),
        Source(kind="x", name="X Feed A", handle="feeda", category="Economics"),
        Source(kind="x", name="X Feed B", handle="feedb", category="Economics"),
    ])
    session.commit()

    rss_ingestor = _ingestor([TWEET_POST], kind="rss")

    hydrated = RawPost(
        external_id="1839000000000000005",
        url="https://x.com/foo/status/1839000000000000005",
        title="hydrated", author_name="foo", author_handle="@foo",
        published_at=datetime(2026, 9, 17, 14, 6, tzinfo=UTC),
    )

    x_ingestor = MagicMock()
    x_ingestor.kind = "x"
    x_ingestor.fetch.side_effect = [[hydrated], []]

    run_ingest(session, ingestors={"rss": rss_ingestor, "x": x_ingestor})

    assert x_ingestor.fetch.call_count == 2
    first_call_source = x_ingestor.fetch.call_args_list[0].args[0]
    second_call_source = x_ingestor.fetch.call_args_list[1].args[0]
    assert first_call_source.pending_tweet_ids == ["1839000000000000005"]
    assert second_call_source.pending_tweet_ids == []
    assert session.query(Post).filter_by(external_id="1839000000000000005").count() == 1


def test_x_source_inserted_before_rss_source_still_gets_discovered_ids(session):
    # The X source has the lower Source.id here -- if the RSS-before-X
    # ordering were only an artifact of ascending id order (rather than a
    # structural partition by kind), this would fail.
    session.add_all([
        Source(kind="x", name="X Feed", handle="feed", category="Economics"),
        Source(kind="rss", name="Reuters", feed_url="https://r.com/rss", category="Economics"),
    ])
    session.commit()

    rss_ingestor = _ingestor([TWEET_POST], kind="rss")
    x_ingestor = _ingestor([], kind="x")

    run_ingest(session, ingestors={"rss": rss_ingestor, "x": x_ingestor})

    x_ingestor.fetch.assert_called_once()
    called_source = x_ingestor.fetch.call_args.args[0]
    assert called_source.pending_tweet_ids == ["1839000000000000005"]


def test_job_run_records_error_status_and_names_failed_sources(session):
    session.add_all([
        Source(kind="rss", name="Broken", feed_url="https://broken.com/rss", category="World"),
        Source(kind="rss", name="Reuters", feed_url="https://r.com/rss", category="Economics"),
    ])
    session.commit()

    ingestor = MagicMock()
    ingestor.kind = "rss"
    ingestor.fetch.side_effect = [httpx.ConnectError("boom"), [POST]]

    run_ingest(session, ingestors={"rss": ingestor})

    run = session.query(JobRun).filter_by(job="ingest").one()
    assert run.status == "error"
    assert "Broken" in run.error
    assert run.items_processed == 1
    assert run.finished_at is not None


def test_default_ingestors_are_closed_after_the_run(session):
    session.add(Source(kind="rss", name="Reuters", feed_url="https://r.com/rss",
                       category="Economics"))
    session.commit()

    mock_rss = _ingestor([], kind="rss")
    mock_x = _ingestor([], kind="x")

    with patch("app.jobs.ingest.RssIngestor", return_value=mock_rss), \
         patch("app.jobs.ingest.XIngestor", return_value=mock_x):
        run_ingest(session)

    mock_rss.close.assert_called_once()
    mock_x.close.assert_called_once()


def test_injected_ingestors_are_not_closed_by_the_job(session):
    session.add(Source(kind="rss", name="Reuters", feed_url="https://r.com/rss",
                       category="Economics"))
    session.commit()

    ingestor = _ingestor([])

    run_ingest(session, ingestors={"rss": ingestor})

    ingestor.close.assert_not_called()
