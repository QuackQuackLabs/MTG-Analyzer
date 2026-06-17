from fastapi.testclient import TestClient

from mtg_analyzer import __version__
from mtg_analyzer.api.app import app

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": __version__}
