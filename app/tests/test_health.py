"""App unit test: the health endpoint responds without needing a database."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))


def test_health_ok(monkeypatch):
    # import lazily so a missing optional dep doesn't break collection of other tests
    import importlib
    app_mod = importlib.import_module("app")
    client = app_mod.app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}
