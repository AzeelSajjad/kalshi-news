from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class RawPost:
    external_id: str
    url: str
    title: str
    body: str | None = None
    author_name: str | None = None
    author_handle: str | None = None
    avatar_url: str | None = None
    published_at: datetime | None = None


class Ingestor(Protocol):
    kind: str

    def fetch(self, source, since: datetime) -> list[RawPost]: ...
