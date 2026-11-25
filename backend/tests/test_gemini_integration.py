"""Gemini provider configuration, payload safety, error/limit/timeout handling, and live API tests."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import init_db
from app.main import app
from app.seed_data import reset_database
from app.services import llm_client


def _setup(tmp_path, monkeypatch):
    test_db = str(tmp_path / "gemini_integration_test.db")
    monkeypatch.setattr(settings, "database_path", test_db)
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "enable_demo_features", True)
    init_db(test_db)
    reset_database(test_db)
    return TestClient(app)


def _login_student(client: TestClient) -> dict[str, str]:
    res = client.post(
        "/api/auth/login",
        json={"identifier": "student@galley.edu", "password": "Student@123"},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_gemini_request_format_header_auth_and_thought_filtering(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch)
    captured = {}

    def fake_post(url, *, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers or {}
        captured["json"] = json
        captured["timeout"] = timeout
        req = httpx.Request("POST", url, headers=headers, json=json)
        return httpx.Response(
            200,
            request=req,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"thought": True, "text": "INTERNAL_THOUGHT_DO_NOT_EXPOSE"},
                                {"text": "Masala Dosa (Rs 55) is available at Main Atrium Galley."},
                            ]
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "llm_api_key", "fake-header-secret-key")
    monkeypatch.setattr(settings, "llm_model", "gemini-2.5-flash")
    monkeypatch.setattr(httpx, "post", fake_post)

    with client:
        h = _login_student(client)
        res = client.post(
            "/api/agents/chat",
            headers=h,
            json={"message": "Do you have veg dosa?"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["ai_mode"] == "live_llm"
        assert body["provider"] == "gemini"
        assert body["model"] == "gemini-2.5-flash"
        assert "INTERNAL_THOUGHT_DO_NOT_EXPOSE" not in body["reply"]
        assert "Masala Dosa" in body["reply"]

        # Verify API key sent via x-goog-api-key header, NEVER in URL query string
        assert "key=" not in captured["url"]
        assert "gemini-2.5-flash:generateContent" in captured["url"]
        assert captured["headers"].get("x-goog-api-key") == "fake-header-secret-key"

        # Zero-arg tools must omit empty 'parameters.properties' to satisfy Gemini v1beta Schema rules
        decls = captured["json"]["tools"][0]["functionDeclarations"]
        for d in decls:
            if "parameters" in d:
                assert d["parameters"].get("properties"), f"Empty properties on tool {d['name']}"


def test_gemini_error_rate_limit_and_timeout_trigger_safe_fallback(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "llm_api_key", "fake-test-key")
    monkeypatch.setattr(settings, "llm_model", "gemini-2.5-flash")

    with client:
        h = _login_student(client)

        # 1. HTTP 429 API quota/rate limit -> transparent deterministic fallback (never exposes key)
        def fake_429(url, *, headers=None, json=None, timeout=None):
            req = httpx.Request("POST", url)
            return httpx.Response(429, request=req, json={"error": {"message": "Quota exceeded"}})

        monkeypatch.setattr(httpx, "post", fake_429)
        r429 = client.post("/api/agents/chat", headers=h, json={"message": "Quick veg food under 60"})
        assert r429.status_code == 200
        assert r429.json()["ai_mode"] == "deterministic_fallback"
        assert "429" in (r429.json()["fallback_reason"] or "")
        assert "fake-test-key" not in (r429.json()["fallback_reason"] or "")

        # 2. HTTP 401 unauthorized API key -> transparent deterministic fallback
        def fake_401(url, *, headers=None, json=None, timeout=None):
            req = httpx.Request("POST", url)
            return httpx.Response(401, request=req, json={"error": {"message": "API key invalid"}})

        monkeypatch.setattr(httpx, "post", fake_401)
        r401 = client.post("/api/agents/chat", headers=h, json={"message": "Fastest outlet?"})
        assert r401.status_code == 200
        assert r401.json()["ai_mode"] == "deterministic_fallback"
        assert "401" in (r401.json()["fallback_reason"] or "")

        # 3. Network timeout -> transparent deterministic fallback
        def fake_timeout(url, *, headers=None, json=None, timeout=None):
            raise httpx.ReadTimeout("Timed out waiting for Gemini")

        monkeypatch.setattr(httpx, "post", fake_timeout)
        rto = client.post("/api/agents/chat", headers=h, json={"message": "Fastest outlet?"})
        assert rto.status_code == 200
        assert rto.json()["ai_mode"] == "deterministic_fallback"
        assert "timed out" in (rto.json()["fallback_reason"] or "").lower()

        # 4. Streaming endpoint timeout/429 -> falls back cleanly with SSE data chunk
        class FailingStream:
            def __enter__(self):
                req = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/test")
                raise httpx.HTTPStatusError(
                    "429",
                    request=req,
                    response=httpx.Response(429, request=req),
                )

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(httpx, "stream", lambda *a, **kw: FailingStream())
        rstream = client.post("/api/agents/chat/stream", headers=h, json={"message": "Menu?"})
        assert rstream.status_code == 200
        assert "deterministic_fallback" in rstream.text
        assert "429" in rstream.text

        # 5. Backend chat rate limiter enforces 429 when exceeding configured quota per minute (4 prior hits)
        monkeypatch.setattr(settings, "chat_rate_limit_per_min", 4)
        monkeypatch.setattr(settings, "llm_api_key", "")
        rlimit = client.post("/api/agents/chat", headers=h, json={"message": "Over rate limit"})
        assert rlimit.status_code == 429
        assert "Retry-After" in rlimit.headers


@pytest.mark.skipif(
    not settings.llm_api_key,
    reason="No real LLM_API_KEY configured in backend/.env or environment; live Gemini call skipped.",
)
def test_live_gemini_real_api_and_followup(tmp_path, monkeypatch):
    """Unmocked end-to-end verification against live Google Gemini API when LLM_API_KEY is present."""
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    client = _setup(tmp_path, monkeypatch)

    with client:
        h = _login_student(client)
        t1 = client.post(
            "/api/agents/chat",
            headers=h,
            json={"message": "Which vegetarian items do you have under 70 rupees?"},
        )
        assert t1.status_code == 200, t1.text
        b1 = t1.json()
        if b1.get("ai_mode") == "deterministic_fallback" and "ConnectError" in str(b1.get("fallback_reason")):
            pytest.skip("Outbound network disabled in current test environment; live Gemini call skipped.")
        assert b1["ai_mode"] == "live_llm", b1
        assert b1["provider"] == "gemini"
        assert b1["fallback_reason"] is None
        conv_id = b1["conversation_id"]

        t2 = client.post(
            "/api/agents/chat",
            headers=h,
            json={
                "conversation_id": conv_id,
                "message": "From those, which one has the shortest wait time right now?",
            },
        )
        assert t2.status_code == 200, t2.text
        b2 = t2.json()
        assert b2["ai_mode"] == "live_llm", b2
        assert b2["conversation_id"] == conv_id
        assert len(b2["reply"].strip()) > 10
