"""seed sources

Nothing in the codebase could create a `sources` row -- no seed, no CLI, no
admin endpoint -- and `kind`, `category` and `enabled` are NOT NULL with
Python-side-only defaults, so a hand-written INSERT that omitted `enabled`
failed outright. A freshly migrated deployment therefore ingested nothing,
which made every downstream stage a no-op. This migration gives the
deployment a working feed registry the moment `alembic upgrade head` runs.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-17

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: str | Sequence[str] | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Every URL below was fetched on 2026-09-17 and returned 200 with an RSS
# body, except the two marked disabled.
#
# Reuters and AP are named in the spec but no longer serve a public RSS feed:
# feeds.reuters.com was retired (the host no longer resolves) and apnews.com
# answers feed paths with a 403 bot challenge. Their rows are seeded with
# their canonical URLs and enabled=false rather than omitted, so re-enabling
# them later is a one-row UPDATE. Leaving them enabled would fail on every
# ingest run, every 10 minutes, marking each run 'error' and burying any real
# failure in the noise.
SOURCES = [
    {"kind": "rss", "name": "Politico Politics",
     "feed_url": "https://rss.politico.com/politics-news.xml",
     "handle": None, "category": "Politics", "enabled": True},
    {"kind": "rss", "name": "Politico Economy",
     "feed_url": "https://rss.politico.com/economy.xml",
     "handle": None, "category": "Economics", "enabled": True},
    {"kind": "rss", "name": "Bloomberg Markets",
     "feed_url": "https://feeds.bloomberg.com/markets/news.rss",
     "handle": None, "category": "Finance", "enabled": True},
    {"kind": "rss", "name": "Bloomberg Politics",
     "feed_url": "https://feeds.bloomberg.com/politics/news.rss",
     "handle": None, "category": "Politics", "enabled": True},
    {"kind": "rss", "name": "CNBC Top News",
     "feed_url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
     "handle": None, "category": "Finance", "enabled": True},
    {"kind": "rss", "name": "CNBC Economy",
     "feed_url": "https://search.cnbc.com/rs/search/combinedcms/view.xml"
                 "?partnerId=wrss01&id=20910258",
     "handle": None, "category": "Economics", "enabled": True},
    {"kind": "rss", "name": "Reuters Top News",
     "feed_url": "https://feeds.reuters.com/reuters/topNews",
     "handle": None, "category": "World", "enabled": False},
    {"kind": "rss", "name": "AP Top News",
     "feed_url": "https://feeds.apnews.com/rss/apf-topnews",
     "handle": None, "category": "World", "enabled": False},
    # X is not polled. The ingest job scans the article bodies the RSS
    # sources return for x.com/status links and queues the tweet IDs on this
    # row, which XIngestor then hydrates once each through the public oEmbed
    # endpoint. It needs no feed_url and no handle -- only a row to hang the
    # hydrated posts off.
    {"kind": "x", "name": "X (links found in articles)",
     "feed_url": None, "handle": None, "category": "World", "enabled": True},
]

sources_table = sa.table(
    "sources",
    sa.column("kind", sa.String),
    sa.column("name", sa.String),
    sa.column("feed_url", sa.String),
    sa.column("handle", sa.String),
    sa.column("category", sa.String),
    sa.column("enabled", sa.Boolean),
)


def upgrade() -> None:
    # A DB-side default so a hand-written INSERT (psql, a fixture, another
    # migration) no longer has to know that the Python model defaults it.
    op.alter_column("sources", "enabled", server_default=sa.text("true"))

    # Idempotent: re-running skips rows already present by name, so this can
    # be replayed against a database seeded by an earlier run without
    # duplicating feeds.
    existing = {
        row[0] for row in op.get_bind().execute(sa.text("SELECT name FROM sources"))
    }
    pending = [source for source in SOURCES if source["name"] not in existing]
    if pending:
        op.bulk_insert(sources_table, pending)


def downgrade() -> None:
    # Only removes seeded rows that nothing references. A source that has
    # already ingested posts is left alone rather than failing the downgrade
    # on the posts.source_id foreign key.
    op.get_bind().execute(
        sa.text(
            "DELETE FROM sources WHERE name = ANY(:names) "
            "AND id NOT IN (SELECT source_id FROM posts)"
        ),
        {"names": [source["name"] for source in SOURCES]},
    )
    op.alter_column("sources", "enabled", server_default=None)
