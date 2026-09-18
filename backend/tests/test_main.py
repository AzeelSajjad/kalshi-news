from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok_when_the_database_is_reachable():
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_returns_503_when_the_database_is_unreachable(monkeypatch):
    """A static {"status": "ok"} dict means a deployed instance with an
    unreachable database still reports healthy and keeps receiving traffic.
    /health must actually execute a query."""

    def broken_get_session():
        raise RuntimeError("connection refused")

    monkeypatch.setattr("app.main.get_session", broken_get_session)

    response = TestClient(app).get("/health")

    assert response.status_code == 503
    assert response.json()["status"] != "ok"
