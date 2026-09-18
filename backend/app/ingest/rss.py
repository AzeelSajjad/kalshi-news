from calendar import timegm
from datetime import UTC, datetime

import feedparser
import httpx

from app.ingest.base import RawPost, strip_html


class RssIngestor:
    kind = "rss"

    def __init__(self, timeout: float = 20.0):
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def fetch(self, source, since: datetime) -> list[RawPost]:
        response = self._client.get(source.feed_url)
        response.raise_for_status()
        feed = feedparser.parse(response.text)

        posts: list[RawPost] = []
        for entry in feed.entries:
            published = self._published(entry)
            if published is None or published <= since:
                continue
            url = entry.get("link", "")
            # Politico, Bloomberg and CNBC all serve markup inside
            # <description>. Stored verbatim it renders as literal "<p>" and
            # "<a href=...>" in the post view and pollutes the embedding, so
            # the body is reduced to prose here. The original markup rides
            # along on raw_html because tweet discovery reads hrefs, which
            # the stripped body no longer has.
            summary = (entry.get("summary") or "").strip() or None
            posts.append(RawPost(
                external_id=entry.get("id") or url,
                url=url,
                title=strip_html(entry.get("title", "")),
                body=strip_html(summary) or None,
                author_name=source.name,
                published_at=published,
                raw_html=summary,
            ))
        return posts

    @staticmethod
    def _published(entry) -> datetime | None:
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed is None:
            return None
        return datetime.fromtimestamp(timegm(parsed), tz=UTC)
