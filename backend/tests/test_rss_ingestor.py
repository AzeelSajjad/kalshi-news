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


# --- HTML in <description> -------------------------------------------------
#
# Politico, Bloomberg and CNBC all put markup in <description>. feedparser
# returns it verbatim, and the frontend renders the stored body as a React
# text node -- so unstripped markup shows up as literal "<p>" and
# "<a href=...>" on the page. It also degrades the text the embedder sees.
# Stripping belongs at ingest, so the stored body and the embedded text are
# the same clean prose.

HTML_FEED = (Path(__file__).parent / "fixtures" / "politico_html.xml").read_text()
HTML_SOURCE = Source(id=2, kind="rss", name="Politico Politics",
                     feed_url="https://example.com/politico-rss", category="Politics")


@respx.mock
def test_body_is_clean_prose_when_the_description_contains_markup():
    respx.get(HTML_SOURCE.feed_url).mock(return_value=httpx.Response(200, text=HTML_FEED))

    posts = RssIngestor().fetch(HTML_SOURCE, since=datetime(2026, 9, 1, tzinfo=UTC))

    body = posts[0].body
    assert body is not None
    assert "<" not in body and ">" not in body, body
    assert "href" not in body
    assert "&mdash;" not in body and "&amp;" not in body
    assert body == (
        "Congressional leaders left the room without a deal, according to two aides. "
        "A shutdown now looks likely — the deadline is Sept 30."
    )


@respx.mock
def test_original_markup_is_preserved_for_tweet_discovery():
    """Stripping tags removes hrefs, and an href is where tweet URLs live.

    The ingest job scans article markup for x.com/status links; if the only
    text it ever sees is stripped prose, the entire X ingestion path goes
    silently dead. The unstripped source is carried alongside the clean body
    for that one purpose.
    """
    from app.ingest.x import extract_tweet_ids

    respx.get(HTML_SOURCE.feed_url).mock(return_value=httpx.Response(200, text=HTML_FEED))

    posts = RssIngestor().fetch(HTML_SOURCE, since=datetime(2026, 9, 1, tzinfo=UTC))

    assert extract_tweet_ids(posts[1].raw_html or "") == ["1839000000000000005"]
