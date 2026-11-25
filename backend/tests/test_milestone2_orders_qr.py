"""Milestone 2 tests: ordering, substitutes, simulated payment, QR reuse guard, and refund rules."""

from fastapi.testclient import TestClient

from app.config import settings
from app.database import init_db
from app.main import app
from app.seed_data import reset_database


def _setup_client(tmp_path, monkeypatch):
    test_db = str(tmp_path / "m2_test.db")
    monkeypatch.setattr(settings, "database_path", test_db)
    init_db(test_db)
    reset_database(test_db)
    return TestClient(app)


def _auth_headers(client: TestClient, identifier: str, password: str) -> dict[str, str]:
    res = client.post("/api/auth/login", json={"identifier": identifier, "password": password})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_out_of_stock_returns_smart_substitute(tmp_path, monkeypatch):
    with _setup_client(tmp_path, monkeypatch) as client:
        stu = _auth_headers(client, "student@galley.edu", "Student@123")
        cat = client.get("/api/catalog/overview", headers=stu).json()
        fried_rice = next(i for i in cat["menu_items"] if i["name"] == "Veg Fried Rice")

        res = client.post(
            "/api/orders/checkout",
            headers=stu,
            json={
                "outlet_id": fried_rice["outlet_id"],
                "student_name": "Kiran",
                "items": [{"menu_item_id": fried_rice["id"], "quantity": 1}],
                "simulate_payment_success": True,
            },
        )
        assert res.status_code == 409
        detail = res.json()["detail"]
        assert detail["unavailable_item_name"] == "Veg Fried Rice"
        assert detail["substitute"]["name"] == "Veg Hakka Noodles"


def test_failed_simulated_payment_preserves_stock(tmp_path, monkeypatch):
    with _setup_client(tmp_path, monkeypatch) as client:
        stu = _auth_headers(client, "student@galley.edu", "Student@123")
        adm = _auth_headers(client, "admin@galley.edu", "Admin@123")
        cat = client.get("/api/catalog/overview", headers=stu).json()
        dosa = next(i for i in cat["menu_items"] if i["name"] == "Masala Dosa")
        orig_stock = dosa["stock_qty"]

        res = client.post(
            "/api/orders/checkout",
            headers=stu,
            json={
                "outlet_id": dosa["outlet_id"],
                "student_name": "Riya",
                "items": [{"menu_item_id": dosa["id"], "quantity": 2}],
                "simulate_payment_success": False,
            },
        )
        assert res.status_code == 402

        cat_after = client.get("/api/catalog/overview", headers=stu).json()
        dosa_after = next(i for i in cat_after["menu_items"] if i["id"] == dosa["id"])
        assert dosa_after["stock_qty"] == orig_stock

        events = client.get("/api/qr/security-events", headers=adm).json()["events"]
        assert any(e["event_type"] == "SIMULATED_PAYMENT_FAILED" for e in events)


def test_checkout_qr_collection_and_duplicate_rejection(tmp_path, monkeypatch):
    with _setup_client(tmp_path, monkeypatch) as client:
        stu = _auth_headers(client, "student@galley.edu", "Student@123")
        mgr = _auth_headers(client, "manager@galley.edu", "Manager@123")
        cat = client.get("/api/catalog/overview", headers=stu).json()
        dosa = next(i for i in cat["menu_items"] if i["name"] == "Masala Dosa")

        checkout = client.post(
            "/api/orders/checkout",
            headers=stu,
            json={
                "outlet_id": dosa["outlet_id"],
                "student_name": "Ananya",
                "items": [{"menu_item_id": dosa["id"], "quantity": 2}],
                "group_code": "GRP-BMS",
                "scheduled_slot": "11:00 Break",
                "simulate_payment_success": True,
            },
        )
        assert checkout.status_code == 200
        order_data = checkout.json()
        assert order_data["payment_status"] == "PAID_SIMULATED"
        assert order_data["order_status"] == "PLACED"
        assert order_data["qr_image"].startswith("data:image/png;base64,")
        token = order_data["qr_token"]

        # Verify group ordering endpoint aggregates correctly
        grp = client.get("/api/orders/group/GRP-BMS", headers=stu).json()
        assert grp["member_count"] == 1
        assert grp["combined_total"] == order_data["total_amount"]

        # First QR scan by Outlet Manager -> Valid & Collected
        scan1 = client.post("/api/qr/verify", headers=mgr, json={"token": token})
        assert scan1.status_code == 200
        assert scan1.json()["valid"] is True
        assert scan1.json()["reason"] == "COLLECTED_OK"

        # Second scan of same QR -> Deterministically Rejected + Security Event logged
        scan2 = client.post("/api/qr/verify", headers=mgr, json={"token": token})
        assert scan2.status_code == 200
        assert scan2.json()["valid"] is False
        assert scan2.json()["reason"] == "DUPLICATE_QR_REUSE"
        assert scan2.json()["risk_level"] == "HIGH"

        events = client.get("/api/qr/security-events", headers=mgr).json()["events"]
        assert any(
            e["event_type"] == "DUPLICATE_QR_REUSE" and e["token"] == token
            for e in events
        )

        # Refund attempt on ALREADY COLLECTED order -> Escalated for Human Review
        refund_attempt = client.post(
            f"/api/orders/{order_data['order_id']}/cancel",
            headers=stu,
            json={"reason": "Want refund after pickup"},
        )
        assert refund_attempt.status_code == 200
        assert refund_attempt.json()["refund_approved"] is False
        assert refund_attempt.json()["requires_human_review"] is True


def test_uncollected_order_cancellation_and_demo_reset(tmp_path, monkeypatch):
    with _setup_client(tmp_path, monkeypatch) as client:
        stu = _auth_headers(client, "student@galley.edu", "Student@123")
        mgr = _auth_headers(client, "manager@galley.edu", "Manager@123")
        adm = _auth_headers(client, "admin@galley.edu", "Admin@123")

        cat = client.get("/api/catalog/overview", headers=stu).json()
        roll = next(i for i in cat["menu_items"] if i["name"] == "Paneer Roll")
        orig_stock = roll["stock_qty"]

        order = client.post(
            "/api/orders/checkout",
            headers=stu,
            json={
                "outlet_id": roll["outlet_id"],
                "student_name": "Vikram",
                "items": [{"menu_item_id": roll["id"], "quantity": 2}],
                "simulate_payment_success": True,
            },
        ).json()

        cancel = client.post(
            f"/api/orders/{order['order_id']}/cancel",
            headers=stu,
            json={"reason": "Class rescheduled"},
        )
        assert cancel.status_code == 200
        assert cancel.json()["refund_approved"] is True

        # Stock should be restored
        cat_after = client.get("/api/catalog/overview", headers=stu).json()
        roll_after = next(i for i in cat_after["menu_items"] if i["id"] == roll["id"])
        assert roll_after["stock_qty"] == orig_stock

        # Cancelled QR must also be rejected at counter
        scan = client.post("/api/qr/verify", headers=mgr, json={"token": order["qr_token"]}).json()
        assert scan["valid"] is False
        assert scan["reason"] == "CANCELLED_QR_ATTEMPT"

        # Demo reset restores clean state (Admin only) and preserves active Admin login
        reset_res = client.post("/api/demo/reset", headers=adm)
        assert reset_res.status_code == 200
        orders_after = client.get("/api/orders", headers=adm).json()["orders"]
        assert len(orders_after) == 0
        cat_reset = client.get("/api/catalog/overview", headers=adm).json()
        assert [o["id"] for o in cat_reset["outlets"]] == [1, 2, 3]
