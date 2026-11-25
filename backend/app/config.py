"""Application settings loaded from environment variables with dev/prod separation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.path.dirname(BASE_DIR)
for env_file in [
    os.path.join(ROOT_DIR, ".env.local"),
    os.path.join(BASE_DIR, ".env.local"),
    os.path.join(BASE_DIR, ".env"),
    os.path.join(ROOT_DIR, ".env"),
]:
    if os.path.isfile(env_file):
        load_dotenv(env_file, override=False)


def _as_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def normalize_database_url(raw_url: str) -> str:
    """Normalize Postgres scheme strings to SQLAlchemy psycopg3 dialect."""
    url = (raw_url or "").strip()
    if not url:
        return ""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+psycopg" not in url.split("://", 1)[0]:
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


@dataclass
class Settings:
    """Runtime configuration for Galley Control backend."""

    app_name: str = "Galley Control API"
    app_version: str = "2.0.0"
    app_env: str = os.getenv("APP_ENV", "development").strip().lower()

    # Production PostgreSQL URL (e.g. postgresql+psycopg://user:pass@host:5432/db?sslmode=require)
    database_url: str = normalize_database_url(os.getenv("DATABASE_URL", ""))
    # Unpooled/direct PostgreSQL URL for DDL/migrations (bypasses PgBouncer transaction mode)
    database_url_unpooled: str = normalize_database_url(
        os.getenv("DATABASE_URL_UNPOOLED", "")
    )
    # Development SQLite fallback when DATABASE_URL is unset
    database_path: str = os.getenv(
        "DATABASE_PATH", os.path.join(BASE_DIR, "galley_control.db")
    )

    # AI / LLM provider settings (server-side only; never exposed to browser)
    llm_provider: str = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    llm_api_key: str = (
        os.getenv("LLM_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
    ).strip()
    llm_model: str = os.getenv("LLM_MODEL", "gemini-2.5-flash").strip()
    llm_timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "25"))
    chat_rate_limit_per_min: int = int(os.getenv("CHAT_RATE_LIMIT_PER_MIN", "25"))

    # Authentication & Cookie Security
    auth_secret: str = os.getenv(
        "AUTH_SECRET", "galley-control-dev-secret-override-via-AUTH_SECRET"
    ).strip()
    token_ttl_seconds: int = int(os.getenv("TOKEN_TTL_SECONDS", "43200"))
    cookie_name: str = os.getenv("SESSION_COOKIE_NAME", "gc_session").strip()
    cookie_secure: bool = _as_bool(
        os.getenv("COOKIE_SECURE"),
        default=os.getenv("APP_ENV", "development").strip().lower() == "production",
    )
    cookie_samesite: str = os.getenv(
        "COOKIE_SAMESITE",
        "none"
        if os.getenv("APP_ENV", "development").strip().lower() == "production"
        else "lax",
    ).strip().lower()
    login_max_failures: int = int(os.getenv("LOGIN_MAX_FAILURES", "5"))
    login_lockout_seconds: int = int(os.getenv("LOGIN_LOCKOUT_SECONDS", "300"))
    password_reset_ttl_minutes: int = int(os.getenv("PASSWORD_RESET_TTL_MINUTES", "30"))

    # Transactional Email (SMTP for password reset)
    smtp_host: str = os.getenv("SMTP_HOST", "").strip()
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = (os.getenv("SMTP_USER") or os.getenv("SMTP_USERNAME") or "").strip()
    smtp_password: str = (os.getenv("SMTP_PASSWORD") or os.getenv("SMTP_PASS") or "").strip()
    smtp_from: str = (
        os.getenv("SMTP_FROM")
        or os.getenv("SMTP_FROM_EMAIL")
        or os.getenv("SMTP_SENDER")
        or "no-reply@galleycontrol.local"
    ).strip()
    smtp_secure: str = os.getenv("SMTP_SECURE", "auto").strip().lower()
    smtp_timeout_seconds: float = float(os.getenv("SMTP_TIMEOUT_SECONDS", "15"))
    frontend_app_url: str = (
        os.getenv("FRONTEND_APP_URL") or "http://localhost:5174"
    ).strip().rstrip("/")

    # Development-only flags (always forced off in production)
    enable_demo_features: bool = _as_bool(
        os.getenv("ENABLE_DEMO_FEATURES"),
        default=os.getenv("APP_ENV", "development").strip().lower() != "production",
    )

    # Optional one-time production admin bootstrap (creates initial admin only if 0 admins exist)
    bootstrap_admin_email: str = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip()
    bootstrap_admin_password: str = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "").strip()
    bootstrap_admin_name: str = os.getenv("BOOTSTRAP_ADMIN_NAME", "Campus Administrator").strip()

    log_level: str = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    cors_origins: tuple[str, ...] = tuple(
        origin.strip().rstrip("/")
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174",
        ).split(",")
        if origin.strip()
    )

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def effective_demo_mode(self) -> bool:
        return (not self.is_production) and self.enable_demo_features

    def get_database_url(self) -> str:
        """Resolve PostgreSQL URL (or SQLite fallback strictly outside production)."""
        normalized = normalize_database_url(self.database_url)
        if normalized:
            return normalized
        if self.is_production:
            raise RuntimeError(
                "DATABASE_URL (PostgreSQL) is required when APP_ENV=production."
            )
        abs_path = os.path.abspath(self.database_path).replace("\\", "/")
        return f"sqlite:///{abs_path}"

    def get_migration_database_url(self) -> str:
        """Resolve direct/unpooled PostgreSQL URL for DDL/migrations (or fallback to database_url)."""
        normalized_unpooled = normalize_database_url(self.database_url_unpooled)
        if normalized_unpooled:
            return normalized_unpooled
        return self.get_database_url()

    def validate_production_safety(self) -> None:
        """Fail fast on insecure secrets or missing production DB settings."""
        if not self.is_production:
            return
        if not normalize_database_url(self.database_url):
            raise RuntimeError("APP_ENV=production requires DATABASE_URL.")
        if (
            not self.auth_secret
            or len(self.auth_secret) < 24
            or "dev-secret" in self.auth_secret
            or "replace-with" in self.auth_secret
        ):
            raise RuntimeError(
                "APP_ENV=production requires a strong random AUTH_SECRET (>=24 chars)."
            )


settings = Settings()
