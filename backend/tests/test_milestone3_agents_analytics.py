"""Milestone 3 tests: Central Orchestrator, 8 specialised agents, review-to-action, and dashboard."""

from fastapi.testclient import TestClient

from app.config import settings
from app.database import init_db
from app.main import app
from app.seed_data import reset_database


def _setup_client(tmp_path, monkeypatch):
    test_db = str(tmp_path / "m3_test.db")
    monkeypatch.setattr(settings, "database_path", test_db)
    init_db(test_db)
    reset_database(test_db)
    return TestClient(app)


def _auth_headers(client: TestClient, identifier: str, password: str) -> dict[str, str]:
    res = client.post("/api/auth/login", json={"identifier": identifier, "password": password})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_orchestrator_assistant_and_lifecycle_trace(tmp_path, monkeypatch):
    with _setup_client(tmp_path, monkeypatch) as client:
        stu = _auth_headers(client, "student@galley.edu", "Student@123")
        res = client.post(
            "/api/agents/chat",
            headers=stu,
            json={
                "message": "Recommend quick veg food under 60 rupees",
                "student_name": "Neha",
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body["orchestrator"] == "Central Orchestrator Agent"
        assert "Ordering Agent" in body["agents_invoked"]
        assert "Queue Agent" in body["agents_invoked"]
        assert "Support Agent" in body["agents_invoked"]
        assert all(item["price"] <= 60 for item in body["suggested_items"])
        assert all(k in body["agentic_lifecycle"] for k in ("sense", "think", "act", "explain", "learn"))


def test_review_to_outlet_action_and_dashboard_consolidation(tmp_path, monkeypatch):
    with _setup_client(tmp_path, monkeypatch) as client:
        stu = _auth_headers(client, "student@galley.edu", "Student@123")
        mgr2 = _auth_headers(client, "manager2@galley.edu", "Manager@123")
        adm = _auth_headers(client, "admin@galley.edu", "Admin@123")

        # Submit a new waiting-time complaint at Tech Block Cafe (outlet_id=2) twice to trigger recurring alert
        for idx in range(2):
            r = client.post(
                "/api/reviews",
                headers=stu,
                json={
                    "outlet_id": 2,
                    "student_name": f"Tester {idx+1}",
                    "rating": 2,
                    "comment": "Waited too long in queue during break, service was very slow.",
                },
            )
            assert r.status_code == 200
            data = r.json()
            assert data["sentiment"] == "NEGATIVE"
            assert data["category"] == "Waiting Time"

        # Second complaint should detect recurring issue and create a human-approval recommendation
        assert data["recurring_alert"] is True
        assert data["recommendation_created"] is not None
        rec_id = data["recommendation_created"]["id"]

        # Admin Dashboard consolidates all 8 agents
        dash = client.get("/api/dashboard/summary", headers=adm).json()
        assert len(dash["active_agents"]) == 8
        assert len(dash["outlet_performance"]["outlets"]) == 3
        assert len(dash["analytics"]["demand_heatmap"]) == 3
        assert any(o["outlet_id"] == 2 and "Waiting Time" in o["bottleneck"] for o in dash["outlet_performance"]["outlets"])

        # Assigned Outlet 2 Manager approves the AI recommendation
        approve = client.post(
            f"/api/dashboard/recommendations/{rec_id}",
            headers=mgr2,
            json={"status": "APPROVED"},
        )
        assert approve.status_code == 200
        assert approve.json()["status"] == "APPROVED"

        # Assigned Outlet 2 Manager marks review resolved
        res_rev = client.post(f"/api/reviews/{data['review_id']}/resolve", headers=mgr2)
        assert res_rev.status_code == 200
        assert res_rev.json()["is_resolved"] is True
