import socket

import pytest
from pytest_socket import SocketConnectBlockedError
from sqlalchemy import text


def test_outbound_sockets_to_non_allowed_hosts_are_blocked():
    """Pins the suite-wide guard in conftest.py's _block_outbound_sockets
    fixture. "No test may make a live external API call" must be an
    enforced invariant, not a convention every test author remembers to
    uphold -- our own mutation-testing of app/api.py showed what happens
    otherwise: a real HTTP request reached the live Kalshi API from inside
    the test suite. Any outbound connection to a host other than the local
    Postgres instance must now fail immediately and loudly.
    """
    with pytest.raises(SocketConnectBlockedError):
        socket.create_connection(("8.8.8.8", 80), timeout=1)


def test_the_local_postgres_connection_the_suite_needs_still_works(session):
    """The guard allowlists localhost/127.0.0.1 so it doesn't also break
    the suite's own DB fixture."""
    assert session.execute(text("SELECT 1")).scalar() == 1
