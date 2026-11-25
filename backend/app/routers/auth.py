"""Authentication routes: multi-tenant registration, login, logout, password reset."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field

from app.config import settings
from app.services.auth_service import (
    authenticate_user,
    bearer_scheme,
    clear_auth_cookie,
    complete_password_reset,
    extract_request_token,
    get_current_user,
    initiate_password_reset,
    register_student,
    revoke_session_token,
    set_auth_cookie,
)
from app.services.email_service import is_email_configured

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    identifier: str | None = Field(default=None, description="Email address or username")
    email: str | None = None
    username: str | None = None
    password: str = Field(..., min_length=1, max_length=72)


class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    username: str = Field(..., min_length=3, max_length=32)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=72)
    confirm_password: str = Field(..., min_length=8, max_length=72)
    organisation_id: int | None = None
    organisation_slug: str | None = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=16, max_length=256)
    new_password: str = Field(..., min_length=8, max_length=72)
    confirm_password: str = Field(..., min_length=8, max_length=72)


@router.get("/config")
def get_auth_config() -> dict:
    """Expose non-sensitive auth & tenant-onboarding capabilities."""
    return {
        "environment": settings.app_env,
        "demo_mode": settings.effective_demo_mode,
        "registration_enabled": True,
        "org_onboarding_enabled": True,
        "email_reset_configured": is_email_configured(),
        "ai_provider": settings.llm_provider or "unconfigured",
        "ai_live_configured": bool(settings.llm_api_key),
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, response: Response) -> dict:
    """Register a student under a verified ACTIVE organisation (never manager/admin)."""
    session = register_student(
        full_name=payload.full_name,
        username=payload.username,
        email=str(payload.email),
        password=payload.password,
        confirm_password=payload.confirm_password,
        organisation_id=payload.organisation_id,
        organisation_slug=payload.organisation_slug,
        request=request,
    )
    set_auth_cookie(response, session["access_token"])
    return session


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    """Authenticate student, outlet/org manager, or platform admin credentials."""
    login_id = payload.identifier or payload.email or payload.username
    if not login_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide identifier, email, or username.",
        )
    session = authenticate_user(login_id, payload.password, request=request)
    set_auth_cookie(response, session["access_token"])
    return session


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Revoke active session token and clear HTTP-only session cookie."""
    token = extract_request_token(request, credentials)
    ip = request.client.host if request.client else None
    if token:
        revoke_session_token(
            token,
            actor_user_id=current_user["id"],
            organisation_id=current_user.get("organisation_id"),
            ip=ip,
        )
    clear_auth_cookie(response)
    return {"status": "logged_out", "username": current_user["username"]}


@router.get("/me")
def me(current_user: dict = Depends(get_current_user)) -> dict:
    """Return the authenticated user's profile, tenant, outlet, and role permissions."""
    return {"user": current_user}


@router.get("/email-status")
def email_status() -> dict:
    """Return operational status of outgoing email delivery (no credentials leaked)."""
    configured = is_email_configured()
    return {
        "configured": configured,
        "mode": "smtp" if configured else "unconfigured",
        "sender": settings.smtp_from if configured else None,
        "host": settings.smtp_host if configured else None,
        "port": settings.smtp_port if configured else None,
        "secure": settings.smtp_secure if configured else None,
    }


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, request: Request) -> dict:
    """Initiate a secure time-limited password reset flow."""
    return initiate_password_reset(str(payload.email), request=request)


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, request: Request) -> dict:
    """Complete password reset using a valid single-use reset token."""
    return complete_password_reset(
        token=payload.token,
        new_password=payload.new_password,
        confirm_password=payload.confirm_password,
        request=request,
    )
