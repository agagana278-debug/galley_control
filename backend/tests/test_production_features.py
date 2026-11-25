"""Tests for Phase 1–5 production capabilities: registration, HTTP-only cookies, reset, rate limits, AI tools/history/streaming, Alembic & prod mode."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.database import db_session, init_db
from app.main import app
from app.models import AuditLog, PasswordResetToken, User
from app.seed_data import reset_database


def _setup(tmp_path, monkeypatch):
    test_db = str(tmp_path / "prod_test.db")
    monkeypatch.setattr(settings, "database_path", test_db)
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "llm_api_key", "")
    init_db(test_db)
    reset_database(test_db)
    return test_db, TestClient(app)


def test_student_registration_cookie_auth_and_role_escalation_blocked(tmp_path, monkeypatch):
    _db_path, client = _setup(tmp_path, monkeypatch)
    with client:
        # Attempt public registration injecting role="admin" -> server MUST ignore and force "student"
        reg = client.post(
            "/api/auth/register",
            json={
                "full_name": "Priya Nair",
                "username": "priya_nair",
                "email": "priya@campus.edu",
                "password": "Password123",
                "confirm_password": "Password123",
                "role": "admin",
            },
        )
        assert reg.status_code == 201
        body = reg.json()
        assert body["user"]["role"] == "student"
        assert body["user"]["outlet_id"] is None
        assert settings.cookie_name in reg.cookies

        # Cookie-only request succeeds on /api/auth/me without Bearer header
        me = client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["user"]["username"] == "priya_nair"

        # Duplicate registration rejected with 409
        dup = client.post(
            "/api/auth/register",
            json={
                "full_name": "Priya 2",
                "username": "priya_nair",
                "email": "priya2@campus.edu",
                "password": "Password123",
                "confirm_password": "Password123",
            },
        )
        assert dup.status_code == 409

        # Admin endpoint still blocked for registered student
        assert client.get("/api/admin/overview").status_code == 403


def test_login_rate_limiting_and_password_reset_revokes_old_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures", 3)
    test_db, client = _setup(tmp_path, monkeypatch)
    with client:
        client.post(
            "/api/auth/register",
            json={
                "full_name": "Arjun Mehta",
                "username": "arjun_m",
                "email": "arjun@campus.edu",
                "password": "OldPassword1",
                "confirm_password": "OldPassword1",
            },
        )
        # Capture bearer token before testing lockout
        login_ok = client.post(
            "/api/auth/login",
            json={"identifier": "arjun_m", "password": "OldPassword1"},
        )
        assert login_ok.status_code == 200
        old_token = login_ok.json()["access_token"]

        # Exhaust login failures -> 429 lockout
        for _ in range(3):
            r = client.post("/api/auth/login", json={"identifier": "arjun_m", "password": "Wrong1234"})
            assert r.status_code == 401
        blocked = client.post("/api/auth/login", json={"identifier": "arjun_m", "password": "OldPassword1"})
        assert blocked.status_code == 429

        # Password reset request returns safe non-leaking response
        fp = client.post("/api/auth/forgot-password", json={"email": "arjun@campus.edu"})
        assert fp.status_code == 200
        assert "raw" not in fp.json()

        # Issue verified single-use token in DB (simulating email link delivery)
        raw_reset = secrets.token_urlsafe(32)
        with db_session(test_db) as db:
            user = db.execute(select(User).where(User.email == "arjun@campus.edu")).scalar_one()
            db.add(
                PasswordResetToken(
                    user_id=user.id,
                    token_hash=hashlib.sha256(raw_reset.encode("utf-8")).hexdigest(),
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
                )
            )

        reset = client.post(
            "/api/auth/reset-password",
            json={
                "token": raw_reset,
                "new_password": "NewPassword99",
                "confirm_password": "NewPassword99",
            },
        )
        assert reset.status_code == 200

        # Old bearer token must now be revoked (401)
        assert (
            client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_token}"}).status_code
            == 401
        )
        # Same reset token cannot be reused
        reuse = client.post(
            "/api/auth/reset-password",
            json={
                "token": raw_reset,
                "new_password": "AnotherPassword99",
                "confirm_password": "AnotherPassword99",
            },
        )
        assert reuse.status_code == 400


def test_admin_can_provision_manager_and_audit_logs_persist(tmp_path, monkeypatch):
    test_db, client = _setup(tmp_path, monkeypatch)
    with client:
        adm = client.post(
            "/api/auth/login", json={"identifier": "admin@galley.edu", "password": "Admin@123"}
        )
        adm_h = {"Authorization": f"Bearer {adm.json()['access_token']}"}

        created = client.post(
            "/api/admin/users",
            headers=adm_h,
            json={
                "full_name": "Hostel Manager",
                "username": "hostel_mgr",
                "email": "hostel_mgr@galley.edu",
                "password": "ManagerPass1",
                "role": "outlet_manager",
                "outlet_id": 3,
            },
        )
        assert created.status_code == 201
        assert created.json()["user"]["outlet_id"] == 3

        with db_session(test_db) as db:
            logs = db.execute(select(AuditLog).where(AuditLog.action == "ADMIN_CREATED_USER")).scalars().all()
            assert len(logs) == 1


def test_multiturn_chatbot_history_followups_role_tools_and_streaming(tmp_path, monkeypatch):
    _test_db, client = _setup(tmp_path, monkeypatch)
    with client:
        stu_tok = client.post(
            "/api/auth/login", json={"identifier": "student@galley.edu", "password": "Student@123"}
        ).json()["access_token"]
        stu_h = {"Authorization": f"Bearer {stu_tok}"}

        # Turn 1: Veg query + typo ("sandwitch" / "dosa")
        t1 = client.post(
            "/api/agents/chat",
            headers=stu_h,
            json={"message": "Show veg food under 60 rupees"},
        )
        assert t1.status_code == 200
        b1 = t1.json()
        conv_id = b1["conversation_id"]
        assert conv_id is not None
        assert b1["ai_mode"] == "deterministic_fallback"
        assert "LLM_API_KEY" in b1["fallback_reason"]
        assert all(i["price"] <= 60 for i in b1["suggested_items"])

        # Turn 2: Follow-up on same conversation ("What about under 45?") preserves veg filter
        t2 = client.post(
            "/api/agents/chat",
            headers=stu_h,
            json={"conversation_id": conv_id, "message": "What about under 45?"},
        )
        assert t2.status_code == 200
        b2 = t2.json()
        assert b2["conversation_id"] == conv_id
        assert all(i["price"] <= 45 for i in b2["suggested_items"])

        # Turn 3: Check persisted conversation history
        hist = client.get(f"/api/agents/conversations/{conv_id}", headers=stu_h)
        assert hist.status_code == 200
        assert len(hist.json()["messages"]) == 4

        # Streaming SSE endpoint emits meta, token, and done frames
        stream_res = client.post(
            "/api/agents/chat/stream",
            headers=stu_h,
            json={"conversation_id": conv_id, "message": "How does QR pickup work?"},
        )
        assert stream_res.status_code == 200
        assert '"type": "meta"' in stream_res.text
        assert '"type": "token"' in stream_res.text
        assert '"type": "done"' in stream_res.text

        # Test real LLM tool-calling flow with mocked OpenAI-compatible HTTP response
        monkeypatch.setattr(settings, "llm_provider", "openai")
        monkeypatch.setattr(settings, "llm_api_key", "test-fake-key-for-mock")
        monkeypatch.setattr(settings, "llm_model", "gpt-4o-mini")

        calls = {"count": 0}

        class _MockResp:
            def __init__(self, data):
                self._data = data

            def raise_for_status(self):
                return None

            def json(self):
                return self._data

        def _mock_httpx_post(_url, headers=None, json=None, timeout=None):
            calls["count"] += 1
            if calls["count"] == 1:
                return _MockResp(
                    {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [
                                        {
                                            "id": "call_1",
                                            "type": "function",
                                            "function": {
                                                "name": "get_inventory_status",
                                                "arguments": "{}",
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                )
            return _MockResp(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Verified DB Inventory: Main Atrium Galley currently has Veg Fried Rice out of stock (0 units).",
                            }
                        }
                    ]
                }
            )

        import app.services.llm_client as llm_mod

        monkeypatch.setattr(llm_mod.httpx, "post", _mock_httpx_post)

        # Outlet manager triggers live tool-calling loop with real DB tool output
        mgr_tok = client.post(
            "/api/auth/login", json={"identifier": "manager@galley.edu", "password": "Manager@123"}
        ).json()["access_token"]
        mgr_h = {"Authorization": f"Bearer {mgr_tok}"}
        mgr_chat = client.post(
            "/api/agents/chat",
            headers=mgr_h,
            json={"message": "Check my outlet stockouts right now"},
        )
        assert mgr_chat.status_code == 200
        m_body = mgr_chat.json()
        assert m_body["ai_mode"] == "live_llm"
        assert "Inventory Agent" in m_body["agents_invoked"]
        assert "Veg Fried Rice" in m_body["reply"]


def test_production_mode_blocks_demo_reset_and_hides_demo_mode(tmp_path, monkeypatch):
    _test_db, client = _setup(tmp_path, monkeypatch)

    with client:
        adm_tok = client.post(
            "/api/auth/login", json={"identifier": "admin@galley.edu", "password": "Admin@123"}
        ).json()["access_token"]

        # Disabling demo features in any env blocks /api/demo/reset and hides demo_mode
        monkeypatch.setattr(settings, "enable_demo_features", False)
        cfg_dev = client.get("/api/auth/config").json()
        assert cfg_dev["demo_mode"] is False
        reset_res = client.post("/api/demo/reset", headers={"Authorization": f"Bearer {adm_tok}"})
        assert reset_res.status_code == 403

        # Production startup fail-fast validation checks
        import pytest

        monkeypatch.setattr(settings, "app_env", "production")
        assert settings.effective_demo_mode is False
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            settings.validate_production_safety()

        monkeypatch.setattr(settings, "database_url", "postgresql+psycopg://u:p@localhost:5432/db")
        with pytest.raises(RuntimeError, match="AUTH_SECRET"):
            settings.validate_production_safety()
