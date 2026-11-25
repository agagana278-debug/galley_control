"""Automated SMTP delivery and end-to-end password reset test suite."""

import re
import socket
import threading
import time
from email import message_from_bytes
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.config import settings
from app.database import db_session, init_db
from app.main import app
from app.models import PasswordResetToken
from app.seed_data import reset_database
from app.services.auth_service import _hash_token


class MockSMTPServer:
    """Threaded RFC 5321 socket server capturing real wire-level SMTP transmissions."""

    def __init__(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind(("127.0.0.1", 0))
        self.port = self.server_socket.getsockname()[1]
        self.server_socket.listen(5)
        self.received_messages: list[bytes] = []
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while self._running:
            try:
                self.server_socket.settimeout(0.5)
                client_sock, _ = self.server_socket.accept()
            except (socket.timeout, OSError):
                continue

            try:
                client_sock.sendall(b"220 smtp.galleycontrol.test ESMTP Service Ready\r\n")
                buffer = b""
                data_mode = False
                mail_data = b""

                while True:
                    chunk = client_sock.recv(4096)
                    if not chunk:
                        break
                    buffer += chunk

                    if data_mode:
                        if b"\r\n.\r\n" in buffer:
                            mail_part, rest = buffer.split(b"\r\n.\r\n", 1)
                            mail_data += mail_part
                            self.received_messages.append(mail_data)
                            client_sock.sendall(b"250 2.0.0 OK Message queued for delivery\r\n")
                            data_mode = False
                            buffer = rest
                        else:
                            mail_data += buffer
                            buffer = b""
                    else:
                        while b"\r\n" in buffer:
                            line, buffer = buffer.split(b"\r\n", 1)
                            cmd = line.decode("ascii", errors="ignore").strip().upper()
                            if cmd.startswith("EHLO") or cmd.startswith("HELO"):
                                client_sock.sendall(b"250-smtp.galleycontrol.test\r\n250 HELP\r\n")
                            elif cmd.startswith("MAIL FROM:"):
                                client_sock.sendall(b"250 2.1.0 Sender OK\r\n")
                            elif cmd.startswith("RCPT TO:"):
                                client_sock.sendall(b"250 2.1.5 Recipient OK\r\n")
                            elif cmd == "DATA":
                                data_mode = True
                                mail_data = b""
                                client_sock.sendall(b"354 Start mail input; end with <CRLF>.<CRLF>\r\n")
                                break
                            elif cmd == "QUIT":
                                client_sock.sendall(b"221 2.0.0 Service closing transmission channel\r\n")
                                break
                            elif cmd == "RSET":
                                client_sock.sendall(b"250 2.0.0 OK\r\n")
                            elif cmd == "NOOP":
                                client_sock.sendall(b"250 2.0.0 OK\r\n")
                            else:
                                client_sock.sendall(b"250 2.0.0 OK\r\n")
            except Exception:
                pass
            finally:
                try:
                    client_sock.close()
                except Exception:
                    pass

    def close(self):
        self._running = False
        try:
            self.server_socket.close()
        except Exception:
            pass
        self._thread.join(timeout=2.0)


@pytest.fixture
def smtp_server():
    server = MockSMTPServer()
    yield server
    server.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_db = str(tmp_path / "smtp_test.db")
    monkeypatch.setattr(settings, "database_path", test_db)
    init_db(test_db)
    reset_database(test_db)
    with TestClient(app) as test_client:
        yield test_client


def test_full_smtp_email_delivery_and_password_reset(client, smtp_server, monkeypatch):
    """End-to-end test of real socket-level SMTP email delivery, token extraction, and password reset."""
    # 1. Configure SMTP settings pointing to local test SMTP socket
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
    monkeypatch.setattr(settings, "smtp_port", smtp_server.port)
    monkeypatch.setattr(settings, "smtp_from", "security@galleycontrol.edu")
    monkeypatch.setattr(settings, "smtp_secure", "none")
    monkeypatch.setattr(settings, "frontend_app_url", "http://localhost:5174")

    # 2. Existing session login to verify session revocation later
    old_login = client.post("/api/auth/login", json={"identifier": "student@galley.edu", "password": "Student@123"})
    assert old_login.status_code == 200
    old_token = old_login.json()["access_token"]
    old_headers = {"Authorization": f"Bearer {old_token}"}
    assert client.get("/api/auth/me", headers=old_headers).status_code == 200

    # 3. Request password reset for existing student
    req_res = client.post("/api/auth/forgot-password", json={"email": "student@galley.edu"})
    assert req_res.status_code == 200
    assert "instructions have been issued" in req_res.json()["message"]
    # Ensure no email_delivery status leaks account existence to client
    assert "email_delivery" not in req_res.json()

    # 4. Verify message was received on the SMTP socket
    time.sleep(0.3)
    assert len(smtp_server.received_messages) == 1, "Expected exactly 1 email received over SMTP socket"
    raw_email = smtp_server.received_messages[0]
    from email import policy
    parsed_msg = message_from_bytes(raw_email, policy=policy.default)

    from email.header import decode_header, make_header
    decoded_subject = str(make_header(decode_header(parsed_msg["Subject"])))
    assert "Galley Control" in decoded_subject and "Reset Your Password" in decoded_subject
    assert parsed_msg["From"] == "security@galleycontrol.edu"
    assert "student@galley.edu" in parsed_msg["To"]

    # 5. Extract reset URL and token from email payload
    plain_body = parsed_msg.get_body(preferencelist=("plain",)).get_content()
    match = re.search(r"http://localhost:5174/reset-password\?token=([a-zA-Z0-9_\-]+)", plain_body)
    assert match, f"Reset URL not found in plain body:\n{plain_body}"
    raw_token = match.group(1).strip()
    assert len(raw_token) >= 32

    # 6. Verify token is hashed with SHA-256 in database (raw token never stored)
    with db_session(settings.database_path) as db:
        token_rec = db.execute(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == _hash_token(raw_token))
        ).scalar_one_or_none()
        assert token_rec is not None
        assert token_rec.used_at is None

    # 7. Complete password reset with new secure password
    new_password = "NewStudentSecure@999"
    reset_res = client.post(
        "/api/auth/reset-password",
        json={"token": raw_token, "new_password": new_password, "confirm_password": new_password},
    )
    assert reset_res.status_code == 200
    assert reset_res.json()["status"] == "password_updated"

    # 8. Verify token invalidation: reusing token MUST fail
    reuse_res = client.post(
        "/api/auth/reset-password",
        json={"token": raw_token, "new_password": "AnotherPassword@123", "confirm_password": "AnotherPassword@123"},
    )
    assert reuse_res.status_code == 400
    assert "Invalid or already-used reset token" in reuse_res.json()["detail"]

    # 9. Verify prior session tokens are revoked
    assert client.get("/api/auth/me", headers=old_headers).status_code == 401

    # 10. Verify old password no longer works
    assert client.post("/api/auth/login", json={"identifier": "student@galley.edu", "password": "Student@123"}).status_code == 401

    # 11. Verify new password authenticates successfully
    new_login = client.post("/api/auth/login", json={"identifier": "student@galley.edu", "password": new_password})
    assert new_login.status_code == 200
    assert new_login.json()["user"]["email"] == "student@galley.edu"


def test_generic_response_prevents_account_enumeration(client, smtp_server, monkeypatch):
    """Unknown email returns the exact same generic message without sending an email."""
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
    monkeypatch.setattr(settings, "smtp_port", smtp_server.port)
    monkeypatch.setattr(settings, "smtp_from", "security@galleycontrol.edu")
    monkeypatch.setattr(settings, "smtp_secure", "none")

    res = client.post("/api/auth/forgot-password", json={"email": "nonexistent_ghost_user@campus.edu"})
    assert res.status_code == 200
    assert "instructions have been issued" in res.json()["message"]
    assert "email_delivery" not in res.json()

    time.sleep(0.2)
    assert len(smtp_server.received_messages) == 0, "No email should be dispatched for non-existent account"


def test_smtp_error_handled_gracefully(client, monkeypatch):
    """SMTP connection errors log properly and report delivery failure without pretending success."""
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
    monkeypatch.setattr(settings, "smtp_port", 65432)  # Unbound port
    monkeypatch.setattr(settings, "smtp_from", "security@galleycontrol.edu")
    monkeypatch.setattr(settings, "smtp_secure", "none")
    monkeypatch.setattr(settings, "smtp_timeout_seconds", 1.0)

    # Calling forgot-password should not crash with 500, but report honest failure
    res = client.post("/api/auth/forgot-password", json={"email": "student@galley.edu"})
    assert res.status_code == 200
    assert res.json()["status"] == "delivery_failed"
    assert "Failed to deliver password reset email via SMTP" in res.json()["message"]


def test_unconfigured_smtp_notifies_client(client, monkeypatch):
    """When SMTP is completely unconfigured, endpoint returns clear unconfigured status."""
    monkeypatch.setattr(settings, "smtp_host", "")
    res = client.post("/api/auth/forgot-password", json={"email": "student@galley.edu"})
    assert res.status_code == 200
    assert res.json()["status"] == "unconfigured"
    assert "SMTP email delivery is not configured" in res.json()["message"]


def test_email_status_endpoint(client, monkeypatch):
    """GET /api/auth/email-status returns operational status."""
    monkeypatch.setattr(settings, "smtp_host", "")
    res = client.get("/api/auth/email-status")
    assert res.status_code == 200
    assert res.json()["configured"] is False
    assert res.json()["mode"] == "unconfigured"

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    res = client.get("/api/auth/email-status")
    assert res.status_code == 200
    assert res.json()["configured"] is True
    assert res.json()["mode"] == "smtp"
