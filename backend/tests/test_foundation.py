"""Milestone 1 foundation tests for FastAPI + SQLite setup."""

from fastapi.testclient import TestClient

from app.config import settings
from app.database import db_session, init_db
from app.main import app
from app.seed_data import reset_database


def _auth_headers(client: TestClient, identifier: str, password: str) -> dict[str, str]:
    res = client.post("/api/auth/login", json={"identifier": identifier, "password": password})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_health_and_catalog_foundation(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_galley.db")
    monkeypatch.setattr(settings, "database_path", test_db)
    init_db(test_db)
    reset_database(test_db)

    with TestClient(app) as client:
        res = client.get("/api/health")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["database"] == "sqlite_connected"
        assert body["counts"]["outlets"] == 3
        assert body["counts"]["menu_items"] == 12

        headers = _auth_headers(client, "student@galley.edu", "Student@123")
        cat = client.get("/api/catalog/overview", headers=headers)
        assert cat.status_code == 200
        cat_body = cat.json()
        assert len(cat_body["outlets"]) == 3
        assert len(cat_body["menu_items"]) == 12
        out_of_stock = [i for i in cat_body["menu_items"] if i["stock_qty"] == 0]
        assert len(out_of_stock) == 1
        assert out_of_stock[0]["substitute_name"] == "Veg Hakka Noodles"
