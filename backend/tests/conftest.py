import pytest
from pytest_socket import socket_allow_hosts
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import Base


@pytest.fixture(autouse=True)
def _block_outbound_sockets():
    """Enforce "no test may make a live external API call" as an invariant
    every test gets for free, not a convention each test author has to
    remember to uphold with the right mock/patch. Our own mutation-testing
    of app/api.py demonstrated exactly what happens when that convention is
    the only guard: a real HTTP request reached the live Kalshi API from
    inside the test suite.

    Allows only the local Postgres connection this suite needs (matching
    DATABASE_URL's host); every other outbound socket raises. A test that
    forgets to mock an HTTP call now fails loudly and immediately instead
    of quietly reaching the real internet.

    Deliberately function-scoped, not session-scoped: pytest-socket's own
    `pytest_runtest_teardown` hook calls `_remove_restrictions()` after
    *every* test, unconditionally, which undoes whatever a session-scoped
    fixture set up after just the first test runs. A function-scoped
    (the default) autouse fixture re-applies the restriction before each
    test instead, matching how pytest-socket's own per-test setup/teardown
    hooks are meant to be driven. Verified empirically: a session-scoped
    version of this fixture let an outbound connection through on the
    second test onward.
    """
    socket_allow_hosts(["127.0.0.1", "localhost", "::1"], allow_unix_socket=True)


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(get_settings().database_url)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.rollback()
    for table in reversed(Base.metadata.sorted_tables):
        s.execute(table.delete())
    s.commit()
    s.close()
