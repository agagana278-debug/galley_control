"""Tests for food item image upload, menu updates, and tenant isolation."""

from io import BytesIO
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.database import init_db
from app.main import app
from app.models import MenuItem
from app.seed_data import reset_database


def _setup(tmp_path, monkeypatch):
    test_db = str(tmp_path / "menu_test.db")
    monkeypatch.setattr(settings, "database_path", test_db)
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "llm_api_key", "")
    init_db(test_db)
    reset_database(test_db)
    return test_db, TestClient(app)


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    res = client.post(
        "/api/auth/login",
        json={"identifier": email, "password": password},
    )
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_menu_item_fields_and_catalog(tmp_path, monkeypatch):
    _db, client = _setup(tmp_path, monkeypatch)
    with client:
        stu_headers = _login(client, "student@galley.edu", "Student@123")
        # Catalog overview includes description and image_url for seeded items
        res = client.get("/api/catalog/overview", headers=stu_headers)
        assert res.status_code == 200
        data = res.json()
        assert len(data["menu_items"]) > 0
        first = data["menu_items"][0]
        assert "description" in first
        assert "image_url" in first
        assert first["image_url"] is not None


def test_manager_update_menu_item_and_isolation(tmp_path, monkeypatch):
    _db, client = _setup(tmp_path, monkeypatch)
    with client:
        mgr1_headers = _login(client, "manager@galley.edu", "Manager@123")
        mgr2_headers = _login(client, "manager2@galley.edu", "Manager@123")

        # Manager 1 gets their dashboard items
        dash_res = client.get("/api/dashboard/outlet", headers=mgr1_headers)
        assert dash_res.status_code == 200
        items = dash_res.json()["menu_items"]
        target_item = items[0]
        assert "image_url" in target_item
        assert "description" in target_item

        # Manager 1 updates price, description, and stock
        patch_res = client.patch(
            f"/api/dashboard/outlet/menu/{target_item['id']}",
            headers=mgr1_headers,
            json={
                "name": "Super Masala Dosa Special",
                "price": 65.0,
                "stock_qty": 35,
                "description": "Ultra crispy spiced potato crepe.",
                "is_veg": True,
            },
        )
        assert patch_res.status_code == 200, patch_res.text
        updated = patch_res.json()["menu_item"]
        assert updated["name"] == "Super Masala Dosa Special"
        assert updated["price"] == 65.0
        assert updated["stock_qty"] == 35
        assert updated["description"] == "Ultra crispy spiced potato crepe."

        # Manager 2 is assigned to Outlet 2, cannot modify Manager 1's item
        forbidden_res = client.patch(
            f"/api/dashboard/outlet/menu/{target_item['id']}",
            headers=mgr2_headers,
            json={"price": 99.0},
        )
        assert forbidden_res.status_code == 403


def test_manager_image_upload_and_delete(tmp_path, monkeypatch):
    _db, client = _setup(tmp_path, monkeypatch)
    with client:
        mgr1_headers = _login(client, "manager@galley.edu", "Manager@123")

        dash_res = client.get("/api/dashboard/outlet", headers=mgr1_headers)
        target_item_id = dash_res.json()["menu_items"][0]["id"]

        # Create dummy image bytes
        fake_png = BytesIO(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRfakeimagedata")

        # Upload image
        upload_res = client.post(
            f"/api/dashboard/outlet/menu/{target_item_id}/image",
            headers=mgr1_headers,
            files={"file": ("test_dish.png", fake_png, "image/png")},
        )
        assert upload_res.status_code == 200, upload_res.text
        img_url = upload_res.json()["image_url"]
        assert img_url.startswith("/static/uploads/menu/")

        # Verify static file is reachable
        static_res = client.get(img_url)
        assert static_res.status_code == 200

        # Delete image
        del_res = client.delete(
            f"/api/dashboard/outlet/menu/{target_item_id}/image",
            headers=mgr1_headers,
        )
        assert del_res.status_code == 200
        assert del_res.json()["image_url"] is None
