import httpx
import respx

from app.ingest.x import OEMBED_URL, XIngestor, extract_tweet_ids

ARTICLE = """
<p>As <a href="https://twitter.com/NickTimiraos/status/1839000000000000001">
one reporter noted</a>…</p>
<blockquote class="twitter-tweet">
<a href="https://x.com/federalreserve/status/1839000000000000002?s=20"></a>
</blockquote>
<p>Duplicate: <a href="https://x.com/NickTimiraos/status/1839000000000000001">same</a></p>
<p>Not a tweet: <a href="https://x.com/NickTimiraos">profile</a></p>
"""

OEMBED_PAYLOAD = {
    "author_name": "Nick Timiraos",
    "author_url": "https://twitter.com/NickTimiraos",
    "html": '<blockquote><p>The internal debate has shifted from whether to cut '
            'to <b>how much</b>.</p>&mdash; Nick Timiraos</blockquote>',
    "url": "https://twitter.com/NickTimiraos/status/1839000000000000001",
}


def test_extract_tweet_ids_dedupes_and_ignores_non_status_links():
    assert extract_tweet_ids(ARTICLE) == ["1839000000000000001", "1839000000000000002"]


def test_extract_tweet_ids_handles_html_with_no_tweets():
    assert extract_tweet_ids("<p>nothing here</p>") == []


@respx.mock
def test_hydrate_builds_a_raw_post_with_author_and_clean_text():
    respx.get(OEMBED_URL).mock(return_value=httpx.Response(200, json=OEMBED_PAYLOAD))

    post = XIngestor().hydrate("1839000000000000001")

    assert post.external_id == "1839000000000000001"
    assert post.author_name == "Nick Timiraos"
    assert post.author_handle == "@NickTimiraos"
    assert "how much" in post.title
    assert "<b>" not in post.title          # HTML stripped
    assert post.url == "https://twitter.com/NickTimiraos/status/1839000000000000001"


@respx.mock
def test_hydrate_returns_none_for_deleted_or_protected_tweets():
    respx.get(OEMBED_URL).mock(return_value=httpx.Response(404))

    assert XIngestor().hydrate("1839000000000000009") is None


@respx.mock
def test_hydrate_never_sends_credentials():
    respx.get(OEMBED_URL).mock(return_value=httpx.Response(200, json=OEMBED_PAYLOAD))

    XIngestor().hydrate("1839000000000000001")

    headers = {k.lower() for k in respx.calls[0].request.headers}
    assert "authorization" not in headers
    assert "cookie" not in headers
