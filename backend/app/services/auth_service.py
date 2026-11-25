"""Multi-tenant authentication, student signup, org onboarding, HTTP-only cookies, and RBAC guards."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.database import db_session, get_db
from app.models import (
    Organisation,
    Outlet,
    PasswordResetToken,
    Permission,
    Role,
    RolePermission,
    User,
    UserSession,
)
from app.services.audit_service import record_audit_log
from app.services.email_service import is_email_configured, send_password_reset_email
from app.services.rate_limit import (
    check_and_increment_rate_limit,
    clear_login_failures,
    is_login_blocked,
    record_login_failure,
)

bearer_scheme = HTTPBearer(auto_error=False)

VALID_ROLES = ("student", "outlet_manager", "admin")
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
PASSWORD_MIN_LEN = 8


def _get_auth_secret() -> bytes:
    secret = settings.auth_secret or os.getenv("AUTH_SECRET") or ""
    if not secret:
        raise RuntimeError("AUTH_SECRET must be set.")
    return secret.encode("utf-8")


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    encoded = plain_password.encode("utf-8")
    if len(encoded) > 72:
        raise ValueError("Password exceeds bcrypt 72-byte maximum length.")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    if not plain_password or not password_hash:
        return False
    encoded = plain_password.encode("utf-8")
    if len(encoded) > 72:
        return False
    try:
        return bcrypt.checkpw(encoded, password_hash.encode("utf-8"))
    except ValueError:
        return False


def validate_password_strength(password: str) -> None:
    if len(password) < PASSWORD_MIN_LEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password must be at least {PASSWORD_MIN_LEN} characters long.",
        )
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at most 72 bytes.",
        )
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must include at least one letter and one digit.",
        )


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sign_session_token(
    user_id: int,
    role: str,
    organisation_id: int | None = None,
    ttl_seconds: int | None = None,
) -> tuple[str, str]:
    """Create a signed HMAC-SHA256 token and return `(token, expires_at_iso)`."""
    now = int(time.time())
    ttl = ttl_seconds if ttl_seconds is not None else settings.token_ttl_seconds
    exp = now + ttl
    payload = {
        "sub": user_id,
        "role": role,
        "org": organisation_id,
        "jti": secrets.token_urlsafe(24),
        "iat": now,
        "exp": exp,
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_get_auth_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    token = f"{payload_b64}.{_b64url_encode(sig)}"
    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return token, expires_at


def verify_signed_token(token: str) -> dict[str, Any]:
    """Verify signature and expiration of a bearer/cookie session token."""
    try:
        payload_b64, sig_b64 = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed authentication token.",
        ) from exc

    expected_sig = _b64url_encode(
        hmac.new(_get_auth_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(sig_b64, expected_sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token signature.",
        )

    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Corrupt authentication token payload.",
        ) from exc

    if int(payload.get("exp", 0)) <= int(time.time()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
        )
    return payload


def set_auth_cookie(response: Response, token: str) -> None:
    samesite = (
        settings.cookie_samesite
        if settings.cookie_samesite in ("lax", "strict", "none")
        else "lax"
    )
    secure = True if samesite == "none" else settings.cookie_secure
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=settings.token_ttl_seconds,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    samesite = (
        settings.cookie_samesite
        if settings.cookie_samesite in ("lax", "strict", "none")
        else "lax"
    )
    secure = True if samesite == "none" else settings.cookie_secure
    response.delete_cookie(
        key=settings.cookie_name,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
    )


def _client_ip(request: Request | None) -> str:
    if request is None:
        return "unknown"
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def _serialize_user(
    db: Session,
    user: User,
    outlet_name: str | None,
    org_name: str | None,
    org_status: str | None,
) -> dict[str, Any]:
    perms: list[str] = []
    if user.role_id is not None:
        perms = list(
            db.execute(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == user.role_id)
            ).scalars().all()
        )
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "organisation_id": user.organisation_id,
        "organisation_name": org_name,
        "organisation_status": org_status,
        "outlet_id": user.outlet_id,
        "outlet_name": outlet_name,
        "is_org_manager": bool(user.role == "outlet_manager" and user.outlet_id is None),
        "permissions": perms,
    }


def _create_session_for_user(
    db: Session,
    user: User,
    outlet_name: str | None,
    org_name: str | None,
    org_status: str | None,
    ip_address: str | None,
    user_agent: str | None,
) -> dict[str, Any]:
    token, expires_at = sign_session_token(user.id, user.role, user.organisation_id)
    db.add(
        UserSession(
            token_hash=_hash_token(token),
            user_id=user.id,
            expires_at=expires_at,
            revoked=False,
            ip_address=ip_address,
            user_agent=(user_agent or "")[:255] or None,
        )
    )
    db.flush()
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at,
        "user": _serialize_user(db, user, outlet_name, org_name, org_status),
    }


def _assert_tenant_access_active(user: User, org_status: str | None) -> None:
    if user.role == "admin":
        return
    if user.organisation_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not linked to an active campus organisation.",
        )
    if org_status == "PENDING_APPROVAL":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your organisation is pending platform administrator approval.",
        )
    if org_status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your organisation is currently suspended or inactive.",
        )


def register_organisation_with_manager(
    *,
    org_name: str,
    org_slug: str,
    campus_location: str,
    contact_email: str,
    manager_full_name: str,
    manager_username: str,
    manager_email: str,
    password: str,
    confirm_password: str,
    request: Request | None = None,
) -> dict[str, Any]:
    """Onboard a new campus/canteen organisation in PENDING_APPROVAL state with its initial manager."""
    clean_org = (org_name or "").strip()
    clean_slug = (org_slug or "").strip().lower()
    clean_loc = (campus_location or "").strip()
    clean_contact = (contact_email or "").strip().lower()
    clean_name = (manager_full_name or "").strip()
    clean_user = (manager_username or "").strip().lower()
    clean_m_email = (manager_email or "").strip().lower()
    ip = _client_ip(request)

    if len(clean_org) < 3 or len(clean_org) > 160:
        raise HTTPException(status_code=400, detail="Organisation name must be 3–160 characters.")
    if not SLUG_RE.match(clean_slug):
        raise HTTPException(
            status_code=400,
            detail="Organisation slug must be 3–64 lowercase alphanumeric/hyphen characters.",
        )
    if not USERNAME_RE.match(clean_user):
        raise HTTPException(
            status_code=400,
            detail="Manager username must be 3–32 characters (letters, numbers, underscores).",
        )
    if password != confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match.")
    validate_password_strength(password)

    with db_session() as db:
        check_and_increment_rate_limit(
            db,
            bucket_key=f"org_reg:{ip}",
            max_attempts=8,
            window_seconds=600,
            block_seconds=600,
            error_message="Too many organisation registration requests.",
        )

        dup_org = db.execute(
            select(Organisation).where(
                (Organisation.slug == clean_slug)
                | (func.lower(Organisation.name) == clean_org.lower())
            )
        ).scalar_one_or_none()
        if dup_org:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An organisation with this name or slug is already registered.",
            )

        dup_user = db.execute(
            select(User).where(
                (User.email == clean_m_email) | (User.username == clean_user)
            )
        ).scalar_one_or_none()
        if dup_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Manager username or email is already in use.",
            )

        org = Organisation(
            name=clean_org,
            slug=clean_slug,
            campus_location=clean_loc,
            contact_email=clean_contact,
            status="PENDING_APPROVAL",
        )
        db.add(org)
        db.flush()

        mgr_role = db.execute(select(Role).where(Role.name == "outlet_manager")).scalar_one_or_none()
        mgr_user = User(
            organisation_id=org.id,
            username=clean_user,
            email=clean_m_email,
            full_name=clean_name,
            password_hash=hash_password(password),
            role="outlet_manager",
            role_id=mgr_role.id if mgr_role else None,
            outlet_id=None,
            is_active=True,
            manager_approval_status="PENDING",
        )
        db.add(mgr_user)
        db.flush()

        record_audit_log(
            db,
            organisation_id=org.id,
            action="ORGANISATION_ONBOARDING_SUBMITTED",
            resource_type="organisation",
            resource_id=org.id,
            actor_user_id=mgr_user.id,
            actor_role="outlet_manager",
            ip_address=ip,
            details={"slug": org.slug, "manager_email": clean_m_email},
        )

        return {
            "organisation": {
                "id": org.id,
                "name": org.name,
                "slug": org.slug,
                "campus_location": org.campus_location,
                "status": org.status,
            },
            "manager": {
                "id": mgr_user.id,
                "username": mgr_user.username,
                "email": mgr_user.email,
                "approval_status": mgr_user.manager_approval_status,
            },
            "message": "Organisation submitted for platform administrator approval before sign-in is enabled.",
        }


def register_student(
    *,
    full_name: str,
    username: str,
    email: str,
    password: str,
    confirm_password: str,
    organisation_id: int | None = None,
    organisation_slug: str | None = None,
    request: Request | None = None,
) -> dict[str, Any]:
    """Public registration endpoint: strictly creates Student accounts tied to an ACTIVE organisation."""
    clean_name = (full_name or "").strip()
    clean_username = (username or "").strip().lower()
    clean_email = (email or "").strip().lower()
    ip = _client_ip(request)

    if len(clean_name) < 2 or len(clean_name) > 100:
        raise HTTPException(status_code=400, detail="Full name must be between 2 and 100 characters.")
    if not USERNAME_RE.match(clean_username):
        raise HTTPException(
            status_code=400,
            detail="Username must be 3–32 characters using letters, numbers, or underscores only.",
        )
    if password != confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match.")
    validate_password_strength(password)

    with db_session() as db:
        check_and_increment_rate_limit(
            db,
            bucket_key=f"register:{ip}",
            max_attempts=15,
            window_seconds=300,
            block_seconds=300,
            error_message="Too many registration attempts.",
        )

        org: Organisation | None = None
        if organisation_id is not None:
            org = db.execute(
                select(Organisation).where(Organisation.id == organisation_id)
            ).scalar_one_or_none()
        elif organisation_slug:
            org = db.execute(
                select(Organisation).where(Organisation.slug == organisation_slug.strip().lower())
            ).scalar_one_or_none()
        elif settings.effective_demo_mode:
            active_orgs = db.execute(
                select(Organisation).where(Organisation.status == "ACTIVE").order_by(Organisation.id)
            ).scalars().all()
            if len(active_orgs) == 1:
                org = active_orgs[0]

        if not org:
            raise HTTPException(
                status_code=400,
                detail="Please select a valid active campus organisation.",
            )
        if org.status != "ACTIVE":
            raise HTTPException(
                status_code=403,
                detail="Selected organisation is not active for student registration.",
            )

        dup = db.execute(
            select(User).where(
                (User.email == clean_email) | (User.username == clean_username)
            )
        ).scalar_one_or_none()
        if dup:
            field = "email" if dup.email.lower() == clean_email else "username"
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An account with that {field} already exists.",
            )

        student_role = db.execute(select(Role).where(Role.name == "student")).scalar_one_or_none()
        new_user = User(
            organisation_id=org.id,
            username=clean_username,
            email=clean_email,
            full_name=clean_name,
            password_hash=hash_password(password),
            role="student",
            role_id=student_role.id if student_role else None,
            outlet_id=None,
            is_active=True,
            manager_approval_status="APPROVED",
        )
        db.add(new_user)
        db.flush()

        record_audit_log(
            db,
            organisation_id=org.id,
            action="USER_REGISTERED",
            resource_type="user",
            resource_id=new_user.id,
            actor_user_id=new_user.id,
            actor_role="student",
            ip_address=ip,
            details={"username": clean_username, "email": clean_email, "organisation_id": org.id},
        )
        ua = request.headers.get("user-agent") if request else None
        return _create_session_for_user(db, new_user, None, org.name, org.status, ip, ua)


def authenticate_user(
    identifier: str,
    password: str,
    request: Request | None = None,
) -> dict[str, Any]:
    """Verify credentials with persistent failed-attempt rate limiting and tenant status check."""
    clean_id = (identifier or "").strip()
    if not clean_id or not password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email/username and password are required.",
        )

    ip = _client_ip(request)
    ip_bucket = f"login_ip:{ip}"
    id_bucket = f"login_id:{clean_id.lower()}"

    with db_session() as db:
        for b in (ip_bucket, id_bucket):
            wait_sec = is_login_blocked(db, b)
            if wait_sec:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many failed login attempts. Try again in {wait_sec} seconds.",
                    headers={"Retry-After": str(wait_sec)},
                )

        row = db.execute(
            select(User, Outlet.name, Organisation.name, Organisation.status)
            .outerjoin(Outlet, Outlet.id == User.outlet_id)
            .outerjoin(Organisation, Organisation.id == User.organisation_id)
            .where((User.email == clean_id.lower()) | (User.username == clean_id.lower()))
            .limit(1)
        ).first()

        user_obj: User | None = row[0] if row else None
        outlet_name: str | None = row[1] if row else None
        org_name: str | None = row[2] if row else None
        org_status: str | None = row[3] if row else None

        if not user_obj or not verify_password(password, user_obj.password_hash):
            record_login_failure(db, ip_bucket)
            record_login_failure(db, id_bucket)
            record_audit_log(
                db,
                action="LOGIN_FAILED",
                resource_type="auth",
                resource_id=clean_id.lower(),
                ip_address=ip,
                details={"reason": "invalid_credentials"},
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email/username or password.",
            )

        if not user_obj.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This user account is inactive. Contact your administrator.",
            )

        _assert_tenant_access_active(user_obj, org_status)

        if user_obj.role == "outlet_manager" and user_obj.manager_approval_status != "APPROVED":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Manager account is awaiting administrator approval.",
            )

        clear_login_failures(db, ip_bucket)
        clear_login_failures(db, id_bucket)
        record_audit_log(
            db,
            organisation_id=user_obj.organisation_id,
            action="LOGIN_SUCCESS",
            resource_type="user",
            resource_id=user_obj.id,
            actor_user_id=user_obj.id,
            actor_role=user_obj.role,
            ip_address=ip,
        )
        ua = request.headers.get("user-agent") if request else None
        return _create_session_for_user(
            db, user_obj, outlet_name, org_name, org_status, ip, ua
        )


def initiate_password_reset(email: str, request: Request | None = None) -> dict[str, Any]:
    """Create a time-limited single-use reset token and trigger email dispatch."""
    clean_email = (email or "").strip().lower()
    ip = _client_ip(request)

    # If outgoing SMTP is not configured, reject clearly so users/admins know action is needed
    if not is_email_configured():
        return {
            "status": "unconfigured",
            "email_delivery": "unconfigured",
            "message": (
                "SMTP email delivery is not configured on this server. "
                "Outgoing mail credentials (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM) "
                "must be configured in backend/.env to dispatch password reset emails."
            ),
        }

    delivery_status = {"delivered": False, "mode": "unconfigured"}

    with db_session() as db:
        check_and_increment_rate_limit(
            db,
            bucket_key=f"pwd_reset:{ip}",
            max_attempts=5,
            window_seconds=600,
            block_seconds=600,
            error_message="Too many password reset requests.",
        )

        user = db.execute(select(User).where(User.email == clean_email)).scalar_one_or_none()
        if user and user.is_active:
            raw_token = secrets.token_urlsafe(32)
            expires_at = datetime.now(timezone.utc) + timedelta(
                minutes=settings.password_reset_ttl_minutes
            )
            db.add(
                PasswordResetToken(
                    user_id=user.id,
                    token_hash=_hash_token(raw_token),
                    expires_at=expires_at,
                )
            )
            db.flush()
            reset_url = f"{settings.frontend_app_url}/reset-password?token={raw_token}"
            delivery_status = send_password_reset_email(user.email, user.full_name, reset_url)
            record_audit_log(
                db,
                organisation_id=user.organisation_id,
                action="PASSWORD_RESET_REQUESTED",
                resource_type="user",
                resource_id=user.id,
                actor_user_id=user.id,
                actor_role=user.role,
                ip_address=ip,
                details={"delivery_mode": delivery_status["mode"], "delivered": delivery_status.get("delivered", False)},
            )
            if not delivery_status.get("delivered", False):
                return {
                    "status": "delivery_failed",
                    "email_delivery": delivery_status.get("mode", "smtp_error"),
                    "message": (
                        f"Failed to deliver password reset email via SMTP ({delivery_status.get('mode')}). "
                        "Please verify your SMTP credentials and mail server status."
                    ),
                }

    return {
        "status": "accepted",
        "message": (
            "If an active account exists for that email address, password reset instructions have been issued."
        ),
    }


def complete_password_reset(
    *,
    token: str,
    new_password: str,
    confirm_password: str,
    request: Request | None = None,
) -> dict[str, Any]:
    """Verify single-use reset token, update password hash, and revoke prior sessions."""
    if new_password != confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match.")
    validate_password_strength(new_password)

    clean_tok = (token or "").strip()
    if len(clean_tok) < 16:
        raise HTTPException(status_code=400, detail="Invalid or expired password reset token.")

    now = datetime.now(timezone.utc)
    token_hash = _hash_token(clean_tok)
    ip = _client_ip(request)

    with db_session() as db:
        rec = db.execute(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        ).scalar_one_or_none()

        if not rec or rec.used_at is not None:
            raise HTTPException(status_code=400, detail="Invalid or already-used reset token.")

        exp = rec.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= now:
            raise HTTPException(status_code=400, detail="Password reset token has expired.")

        user = db.execute(select(User).where(User.id == rec.user_id)).scalar_one_or_none()
        if not user or not user.is_active:
            raise HTTPException(status_code=400, detail="Account unavailable for password reset.")

        user.password_hash = hash_password(new_password)
        rec.used_at = now
        db.execute(update(UserSession).where(UserSession.user_id == user.id).values(revoked=True))
        record_audit_log(
            db,
            organisation_id=user.organisation_id,
            action="PASSWORD_RESET_COMPLETED",
            resource_type="user",
            resource_id=user.id,
            actor_user_id=user.id,
            actor_role=user.role,
            ip_address=ip,
        )

    return {"status": "password_updated", "message": "Password updated. You can now sign in."}


def revoke_session_token(
    token: str,
    actor_user_id: int | None = None,
    organisation_id: int | None = None,
    ip: str | None = None,
) -> None:
    """Revoke a session token in the database and log logout."""
    with db_session() as db:
        db.execute(
            update(UserSession)
            .where(UserSession.token_hash == _hash_token(token))
            .values(revoked=True)
        )
        if actor_user_id is not None:
            record_audit_log(
                db,
                organisation_id=organisation_id,
                action="LOGOUT",
                resource_type="user",
                resource_id=actor_user_id,
                actor_user_id=actor_user_id,
                ip_address=ip,
            )


def resolve_user_from_token(token: str, db: Session | None = None) -> dict[str, Any]:
    """Validate token signature, session status, user status, and tenant status from DB."""
    payload = verify_signed_token(token)
    token_hash = _hash_token(token)

    def _lookup(sess: Session) -> dict[str, Any]:
        row = sess.execute(
            select(User, Outlet.name, Organisation.name, Organisation.status, UserSession)
            .join(UserSession, UserSession.user_id == User.id)
            .outerjoin(Outlet, Outlet.id == User.outlet_id)
            .outerjoin(Organisation, Organisation.id == User.organisation_id)
            .where(UserSession.token_hash == token_hash)
            .limit(1)
        ).first()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session is invalid or logged out.",
            )

        user_obj, outlet_name, org_name, org_status, session_obj = row
        if session_obj.revoked or not user_obj.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session is invalid or logged out.",
            )

        if int(user_obj.id) != int(payload.get("sub", -1)):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token subject mismatch.",
            )

        _assert_tenant_access_active(user_obj, org_status)
        if user_obj.role == "outlet_manager" and user_obj.manager_approval_status != "APPROVED":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Manager account approval is pending or revoked.",
            )

        return _serialize_user(sess, user_obj, outlet_name, org_name, org_status)

    if db is not None:
        return _lookup(db)
    with db_session() as sess:
        return _lookup(sess)


def extract_request_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    """Read auth token from Authorization Bearer header or HTTP-only session cookie."""
    if credentials and credentials.scheme.lower() == "bearer" and credentials.credentials:
        return credentials.credentials
    cookie_tok = request.cookies.get(settings.cookie_name)
    if cookie_tok:
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = (request.headers.get("origin") or "").rstrip("/")
            if origin and origin not in settings.cors_origins:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cross-site request origin blocked.",
                )
        return cookie_tok
    return None


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """FastAPI dependency deriving authenticated user + server-verified tenant context."""
    token = extract_request_token(request, credentials)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    return resolve_user_from_token(token, db=db)


def require_roles(*allowed_roles: str):
    """FastAPI dependency enforcing server-side role checks."""

    def _checker(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if current_user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied for role '{current_user['role']}'.",
            )
        return current_user

    return _checker
