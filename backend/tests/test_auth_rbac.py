"""Authentication, session persistence/revocation, and strict RBAC enforcement tests."""

from fastapi.testclient import TestClient

from app.config import settings
from app.database import init_db
from app.main import app
from app.seed_data import reset_database


def _setup_client(tmp_path, monkeypatch):
    test_db = str(tmp_path / "rbac_test.db")
    monkeypatch.setattr(settings, "database_path", test_db)
    init_db(test_db)
    reset_database(test_db)
    return TestClient(app)


def _login(client: TestClient, identifier: str, password: str):
    return client.post("/api/auth/login", json={"identifier": identifier, "password": password})


def test_login_session_persistence_and_logout(tmp_path, monkeypatch):
    with _setup_client(tmp_path, monkeypatch) as client:
        # Invalid credentials rejected
        bad = _login(client, "student@galley.edu", "WrongPassword")
        assert bad.status_code == 401

        # Unauthenticated protected route rejected with 401
        assert client.get("/api/auth/me").status_code == 401
        assert client.get("/api/catalog/overview").status_code == 401

        # Login with username OR email works
        ok = _login(client, "student", "Student@123")
        assert ok.status_code == 200
        body = ok.json()
        token = body["access_token"]
        assert body["user"]["role"] == "student"
        assert body["user"]["email"] == "student@galley.edu"
        headers = {"Authorization": f"Bearer {token}"}

        # Session hydration endpoint (/api/auth/me) succeeds on refresh
        me = client.get("/api/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["user"]["username"] == "student"

        # Logout revokes token in SQLite user_sessions
        out = client.post("/api/auth/logout", headers=headers)
        assert out.status_code == 200
        assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_strict_role_and_outlet_boundaries(tmp_path, monkeypatch):
    with _setup_client(tmp_path, monkeypatch) as client:
        stu_tok = _login(client, "student@galley.edu", "Student@123").json()["access_token"]
        mgr1_tok = _login(client, "manager@galley.edu", "Manager@123").json()["access_token"]
        mgr2_tok = _login(client, "manager2@galley.edu", "Manager@123").json()["access_token"]
        adm_tok = _login(client, "admin@galley.edu", "Admin@123").json()["access_token"]

        stu_h = {"Authorization": f"Bearer {stu_tok}"}
        mgr1_h = {"Authorization": f"Bearer {mgr1_tok}"}
        mgr2_h = {"Authorization": f"Bearer {mgr2_tok}"}
        adm_h = {"Authorization": f"Bearer {adm_tok}"}

        # Student places orders at Outlet 1 and Outlet 2
        cat = client.get("/api/catalog/overview", headers=stu_h).json()
        dosa = next(i for i in cat["menu_items"] if i["outlet_id"] == 1 and i["stock_qty"] > 0)
        coffee = next(i for i in cat["menu_items"] if i["outlet_id"] == 2 and i["stock_qty"] > 0)

        o1 = client.post(
            "/api/orders/checkout",
            headers=stu_h,
            json={"outlet_id": 1, "student_name": "Ananya Sharma", "items": [{"menu_item_id": dosa["id"], "quantity": 1}]},
        ).json()
        o2 = client.post(
            "/api/orders/checkout",
            headers=stu_h,
            json={"outlet_id": 2, "student_name": "Ananya Sharma", "items": [{"menu_item_id": coffee["id"], "quantity": 1}]},
        ).json()

        # Student cannot access manager or admin capabilities
        assert client.post("/api/qr/verify", headers=stu_h, json={"token": o1["qr_token"]}).status_code == 403
        assert client.get("/api/dashboard/outlet", headers=stu_h).status_code == 403
        assert client.get("/api/dashboard/summary", headers=stu_h).status_code == 403
        assert client.get("/api/admin/overview", headers=stu_h).status_code == 403
        assert client.post("/api/demo/reset", headers=stu_h).status_code == 403

        # Outlet Manager 1 can inspect Outlet 1 dashboard, mark Outlet 1 order preparing, restock Outlet 1 item, verify Outlet 1 QR
        dash1 = client.get("/api/dashboard/outlet", headers=mgr1_h)
        assert dash1.status_code == 200
        assert dash1.json()["outlet"]["id"] == 1
        assert all(ord_row["outlet_id"] == 1 for ord_row in dash1.json()["orders"])

        prep1 = client.post(f"/api/orders/{o1['order_id']}/prepare", headers=mgr1_h)
        assert prep1.status_code == 200
        assert prep1.json()["order_status"] == "PREPARING"

        # Outlet Manager 1 CANNOT verify Outlet 2 QR, prepare Outlet 2 order, restock Outlet 2 item, or reach Admin APIs
        assert client.post("/api/qr/verify", headers=mgr1_h, json={"token": o2["qr_token"]}).status_code == 403
        assert client.post(f"/api/orders/{o2['order_id']}/prepare", headers=mgr1_h).status_code == 403
        assert client.patch(f"/api/dashboard/outlet/menu/{coffee['id']}/stock", headers=mgr1_h, json={"stock_qty": 20}).status_code == 403
        assert client.get("/api/dashboard/summary", headers=mgr1_h).status_code == 403
        assert client.get("/api/admin/overview", headers=mgr1_h).status_code == 403
        assert client.patch("/api/admin/outlets/1", headers=mgr1_h, json={"status": "BUSY"}).status_code == 403
        assert client.post("/api/demo/reset", headers=mgr1_h).status_code == 403
        assert client.post("/api/orders/checkout", headers=mgr1_h, json={"outlet_id": 1, "student_name": "X", "items": [{"menu_item_id": dosa["id"], "quantity": 1}]}).status_code == 403

        # Outlet Manager 2 CAN verify Outlet 2 QR
        scan_o2 = client.post("/api/qr/verify", headers=mgr2_h, json={"token": o2["qr_token"]})
        assert scan_o2.status_code == 200
        assert scan_o2.json()["valid"] is True

        # Admin has full campus governance & outlet configuration control
        admin_ov = client.get("/api/admin/overview", headers=adm_h)
        assert admin_ov.status_code == 200
        assert len(admin_ov.json()["outlets"]) == 3
        assert all("password_hash" not in u for u in admin_ov.json()["users"])

        # Closing an outlet as Admin prevents new student orders there
        close_res = client.patch("/api/admin/outlets/3", headers=adm_h, json={"status": "CLOSED", "active_staff": 1})
        assert close_res.status_code == 200
        assert close_res.json()["outlet"]["status"] == "CLOSED"

        night_item = next(i for i in cat["menu_items"] if i["outlet_id"] == 3 and i["stock_qty"] > 0)
        closed_checkout = client.post(
            "/api/orders/checkout",
            headers=stu_h,
            json={"outlet_id": 3, "student_name": "Ananya", "items": [{"menu_item_id": night_item["id"], "quantity": 1}]},
        )
        assert closed_checkout.status_code == 400


def test_existing_db_migration_preserves_orders(tmp_path, monkeypatch):
    legacy_db = str(tmp_path / "legacy_galley.db")
    monkeypatch.setattr(settings, "database_path", legacy_db)
    init_db(legacy_db)
    reset_database(legacy_db)

    from sqlalchemy import text
    from app.database import db_session
    from app.seed_data import seed_database

    with db_session(legacy_db) as conn:
        conn.execute(text("PRAGMA foreign_keys = OFF"))
        conn.execute(text("DROP TABLE IF EXISTS password_reset_tokens"))
        conn.execute(text("DROP TABLE IF EXISTS user_sessions"))
        conn.execute(text("DROP TABLE IF EXISTS ai_messages"))
        conn.execute(text("DROP TABLE IF EXISTS ai_conversations"))
        conn.execute(text("DROP TABLE IF EXISTS users"))
        conn.execute(text("PRAGMA foreign_keys = ON"))
        before_orders = conn.execute(text("SELECT COUNT(*) FROM orders")).scalar_one()

    init_db(legacy_db)
    with db_session(legacy_db) as conn:
        seed_database(conn)
        after_orders = conn.execute(text("SELECT COUNT(*) FROM orders")).scalar_one()
        user_count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar_one()

    assert after_orders == before_orders
    assert user_count == 4

