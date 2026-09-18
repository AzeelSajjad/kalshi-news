import html as html_lib
import re
from datetime import datetime

import httpx

from app.ingest.base import RawPost

OEMBED_URL = "https://publish.twitter.com/oembed"

_STATUS_RE = re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/[^/\s\"']+/status/(\d+)")
_TAG_RE = re.compile(r"<[^>]+>")
_TRAILING_ATTRIB_RE = re.compile(r"&mdash;.*$", re.DOTALL)


def extract_tweet_ids(html: str) -> list[str]:
    seen: dict[str, None] = {}
    for match in _STATUS_RE.finditer(html or ""):
        seen.setdefault(match.group(1), None)
    return list(seen)


def _tweet_text(embed_html: str) -> str:
    text = _TRAILING_ATTRIB_RE.sub("", embed_html or "")
    text = _TAG_RE.sub(" ", text)
    return " ".join(html_lib.unescape(text).split())


class XIngestor:
    """Discovers tweet IDs from article HTML, then hydrates each one exactly once
    through X's public oEmbed endpoint. No scraping, no credentials, no browser."""

    kind = "x"

    def __init__(self, timeout: float = 15.0):
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)

    def hydrate(self, tweet_id: str) -> RawPost | None:
        response = self._client.get(OEMBED_URL, params={
            "url": f"https://twitter.com/i/status/{tweet_id}",
            "omit_script": "true", "dnt": "true",
        })
        if response.status_code in (401, 403, 404):
            return None
        response.raise_for_status()
        payload = response.json()

        author_url = payload.get("author_url") or ""
        handle = author_url.rstrip("/").rsplit("/", 1)[-1]
        return RawPost(
            external_id=tweet_id,
            url=payload.get("url") or author_url,
            title=_tweet_text(payload.get("html", "")),
            body=None,
            author_name=payload.get("author_name"),
            author_handle=f"@{handle}" if handle else None,
            published_at=None,
        )

    def fetch(self, source, since: datetime) -> list[RawPost]:
        """Hydrate any pending tweet IDs queued for this source.

        Discovery happens in the ingest job, which scans fetched article HTML
        with extract_tweet_ids and queues what it finds on the source.
        """
        pending = getattr(source, "pending_tweet_ids", None) or []
        posts = []
        for tweet_id in pending:
            post = self.hydrate(tweet_id)
            if post is not None:
                posts.append(post)
        return posts
