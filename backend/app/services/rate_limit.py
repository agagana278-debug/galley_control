"""Database-backed sliding window rate limiter for auth and AI endpoints."""

from __future__ import annotations

import time
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AuthRateLimit


def check_and_increment_rate_limit(
    db: Session,
    *,
    bucket_key: str,
    max_attempts: int,
    window_seconds: int,
    block_seconds: int,
    error_message: str,
) -> None:
    """Enforce persistent rate limits across requests and workers."""
    now = time.time()
    row = db.execute(
        select(AuthRateLimit).where(AuthRateLimit.bucket_key == bucket_key)
    ).scalar_one_or_none()

    if row and row.blocked_until and row.blocked_until > now:
        retry_after = max(1, int(row.blocked_until - now))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"{error_message} Retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    if not row:
        row = AuthRateLimit(
            bucket_key=bucket_key,
            attempts=1,
            window_started_at=now,
            blocked_until=None,
        )
        db.add(row)
        db.flush()
        return

    if now - row.window_started_at > window_seconds:
        row.attempts = 1
        row.window_started_at = now
        row.blocked_until = None
    else:
        row.attempts += 1
        if row.attempts > max_attempts:
            row.blocked_until = now + block_seconds
            db.flush()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"{error_message} Retry in {block_seconds} seconds.",
                headers={"Retry-After": str(block_seconds)},
            )
    db.flush()


def is_login_blocked(db: Session, bucket_key: str) -> int | None:
    """Return remaining block seconds if login bucket is currently locked out."""
    now = time.time()
    row = db.execute(
        select(AuthRateLimit).where(AuthRateLimit.bucket_key == bucket_key)
    ).scalar_one_or_none()
    if row and row.blocked_until and row.blocked_until > now:
        return max(1, int(row.blocked_until - now))
    return None


def record_login_failure(db: Session, bucket_key: str) -> None:
    """Increment failed login attempts and lock bucket after LOGIN_MAX_FAILURES."""
    now = time.time()
    max_fail = settings.login_max_failures
    lock_sec = settings.login_lockout_seconds
    row = db.execute(
        select(AuthRateLimit).where(AuthRateLimit.bucket_key == bucket_key)
    ).scalar_one_or_none()

    if not row:
        row = AuthRateLimit(
            bucket_key=bucket_key,
            attempts=1,
            window_started_at=now,
            blocked_until=now + lock_sec if max_fail <= 1 else None,
        )
        db.add(row)
    else:
        if now - row.window_started_at > lock_sec:
            row.attempts = 1
            row.window_started_at = now
            row.blocked_until = None
        else:
            row.attempts += 1
            if row.attempts >= max_fail:
                row.blocked_until = now + lock_sec
    db.flush()


def clear_login_failures(db: Session, bucket_key: str) -> None:
    """Reset failed login counter after a successful authentication."""
    row = db.execute(
        select(AuthRateLimit).where(AuthRateLimit.bucket_key == bucket_key)
    ).scalar_one_or_none()
    if row:
        row.attempts = 0
        row.blocked_until = None
        db.flush()
