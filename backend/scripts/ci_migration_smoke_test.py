"""CI smoke test for the alembic-built schema.

`alembic upgrade head && alembic downgrade base` in CI proves the
migrations *run*, but the test suite builds its schema with
`Base.metadata.create_all` (see tests/conftest.py), so nothing has ever
actually written to the schema `alembic upgrade head` produces. A column
whose NOT NULL constraint depends on a migration-only `server_default`
(see migrations/versions/0002_seed_sources.py) could regress silently.

This script inserts a real row into the migrated `sources` table without
supplying `enabled`, reads it back, and asserts the server_default applied
-- then cleans up after itself. Run against a database that already has
`alembic upgrade head` applied; exits non-zero (via the raised
AssertionError) if anything is wrong with the migrated schema.
"""

from sqlalchemy import create_engine, text

from app.config import get_settings

SMOKE_SOURCE_NAME = "CI migration smoke test source"


def main() -> None:
    engine = create_engine(get_settings().database_url)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO sources (kind, name, category) "
            "VALUES ('rss', :name, 'World')"
        ), {"name": SMOKE_SOURCE_NAME})

        row = conn.execute(text(
            "SELECT enabled FROM sources WHERE name = :name"
        ), {"name": SMOKE_SOURCE_NAME}).one()
        assert row.enabled is True, f"expected enabled to default true, got {row.enabled!r}"

        conn.execute(text("DELETE FROM sources WHERE name = :name"), {"name": SMOKE_SOURCE_NAME})

    print("migrated schema smoke test passed")


if __name__ == "__main__":
    main()
