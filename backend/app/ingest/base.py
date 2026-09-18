import html as html_lib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

_TAG_RE = re.compile(r"<[^>]+>")
# A tag becomes a space, which strands one before any punctuation that
# followed a closing tag ("...two aides</a>." -> "...two aides ."). Closing
# that gap here keeps the artifact out of prose a reader actually sees.
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?%)\]}])")
_SPACE_AFTER_OPEN_RE = re.compile(r"([(\[{])\s+")


def strip_html(markup: str | None) -> str:
    """Reduce a fragment of markup to the prose a reader would see.

    Tags become a space (so `<p>A</p><p>B</p>` does not run together as
    "AB"), entities are unescaped, and whitespace is collapsed to single
    spaces. Deliberately dependency-free and shared by every ingestor:
    the X ingestor grew this first, and RSS <description> bodies need
    exactly the same treatment, so there is one definition of "clean
    prose" rather than two that drift.

    Stripping happens at ingest rather than at render because the stored
    body is also what the embedder sees -- markup in the embedded text is
    noise in the vector, not just noise on the page.
    """
    text = _TAG_RE.sub(" ", markup or "")
    text = " ".join(html_lib.unescape(text).split())
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    return _SPACE_AFTER_OPEN_RE.sub(r"\1", text)


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
    # The unstripped source markup, carried for one purpose only: tweet
    # discovery scans it for x.com/status links, and those live in href
    # attributes that `body` no longer contains. Never stored, never
    # embedded, never rendered.
    raw_html: str | None = None


class Ingestor(Protocol):
    kind: str

    def fetch(self, source, since: datetime) -> list[RawPost]: ...
