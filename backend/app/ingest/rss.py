from calendar import timegm
from datetime import UTC, datetime

import feedparser
import httpx

from app.ingest.base import RawPost


class RssIngestor:
    kind = "rss"

    def __init__(self, timeout: float = 20.0):
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)

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
            posts.append(RawPost(
                external_id=entry.get("id") or url,
                url=url,
                title=entry.get("title", "").strip(),
                body=(entry.get("summary") or "").strip() or None,
                author_name=source.name,
                published_at=published,
            ))
        return posts

    @staticmethod
    def _published(entry) -> datetime | None:
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed is None:
            return None
        return datetime.fromtimestamp(timegm(parsed), tz=UTC)
