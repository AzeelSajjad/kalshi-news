from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from app.ingest.rss import RssIngestor
from app.models import Source

FEED = (Path(__file__).parent / "fixtures" / "reuters.xml").read_text()
SOURCE = Source(id=1, kind="rss", name="Reuters",
                feed_url="https://example.com/rss", category="Economics")


@respx.mock
def test_fetch_parses_items_into_raw_posts():
    respx.get(SOURCE.feed_url).mock(return_value=httpx.Response(200, text=FEED))

    posts = RssIngestor().fetch(SOURCE, since=datetime(2026, 9, 1, tzinfo=UTC))

    assert len(posts) == 2
    assert posts[0].title == "Powell signals openness to a September cut"
    assert posts[0].author_name == "Reuters"
    assert posts[0].published_at == datetime(2026, 9, 17, 14, 2, tzinfo=UTC)
    assert posts[0].url.startswith("http")


@respx.mock
def test_fetch_skips_items_older_than_since():
    respx.get(SOURCE.feed_url).mock(return_value=httpx.Response(200, text=FEED))

    posts = RssIngestor().fetch(SOURCE, since=datetime(2026, 9, 17, 13, 30, tzinfo=UTC))

    assert [p.title for p in posts] == ["Powell signals openness to a September cut"]


@respx.mock
def test_external_id_falls_back_to_url_when_guid_missing():
    respx.get(SOURCE.feed_url).mock(return_value=httpx.Response(200, text=FEED))

    posts = RssIngestor().fetch(SOURCE, since=datetime(2026, 9, 1, tzinfo=UTC))

    assert posts[1].external_id == posts[1].url


@respx.mock
def test_http_error_raises_so_the_caller_can_isolate_the_source():
    respx.get(SOURCE.feed_url).mock(return_value=httpx.Response(503))

    with pytest.raises(httpx.HTTPStatusError):
        RssIngestor().fetch(SOURCE, since=datetime(2026, 9, 1, tzinfo=UTC))
