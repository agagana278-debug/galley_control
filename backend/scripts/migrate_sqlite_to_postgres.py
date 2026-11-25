"""Idempotent SQLite -> PostgreSQL data migrator preserving existing records and sequences."""

from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from app.config import normalize_database_url
from app.models import Base

TABLE_COPY_ORDER = [
    "organisations",
    "roles",
    "permissions",
    "role_permissions",
    "outlets",
    "users",
    "user_sessions",
    "password_reset_tokens",
    "auth_rate_limits",
    "menu_items",
    "inventory_movements",
    "orders",
    "order_items",
    "qr_tokens",
    "security_events",
    "reviews",
    "ai_recommendations",
    "ai_conversations",
    "ai_messages",
    "agent_activity_logs",
    "outlet_performance_snapshots",
    "audit_logs",
]

BOOL_COLS = {
    "is_active",
    "revoked",
    "is_veg",
    "is_available",
    "is_sample",
    "requires_human_review",
    "resolved",
    "is_resolved",
}


def _coerce_value(col_name: str, val):
    if val is None:
        return None
    if col_name in BOOL_COLS and isinstance(val, int):
        return bool(val)
    if col_name.endswith("_at") and isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)
    return val


def migrate_sqlite_to_postgres(sqlite_path: str, pg_url: str) -> None:
    if not os.path.exists(sqlite_path):
        raise SystemExit(f"SQLite file not found: {sqlite_path}")
    target_url = normalize_database_url(pg_url)
    if not target_url.startswith("postgresql"):
        raise SystemExit("Target URL must be a PostgreSQL connection string.")

    pg_engine = create_engine(target_url, future=True)
    Base.metadata.create_all(bind=pg_engine, checkfirst=True)

    sq = sqlite3.connect(sqlite_path)
    sq.row_factory = sqlite3.Row
    sq_tables = {
        r[0]
        for r in sq.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    with pg_engine.begin() as conn:
        for table_name in TABLE_COPY_ORDER:
            if table_name not in sq_tables:
                continue
            rows = sq.execute(f"SELECT * FROM {table_name}").fetchall()
            if not rows:
                continue
            pg_cols = set(Base.metadata.tables[table_name].columns.keys())
            existing_count = conn.execute(
                text(f"SELECT COUNT(*) FROM {table_name}")
            ).scalar_one()
            if existing_count > 0:
                print(f"[SKIP] {table_name}: target already has {existing_count} row(s).")
                continue

            src_cols = [c for c in rows[0].keys() if c in pg_cols]
            col_list = ", ".join(src_cols)
            bind_list = ", ".join(f":{c}" for c in src_cols)
            insert_sql = text(
                f"INSERT INTO {table_name} ({col_list}) VALUES ({bind_list})"
            )
            payload = [
                {c: _coerce_value(c, r[c]) for c in src_cols}
                for r in rows
            ]
            conn.execute(insert_sql, payload)
            print(f"[COPIED] {table_name}: {len(payload)} row(s).")

            if "id" in src_cols:
                conn.execute(
                    text(
                        "SELECT setval(pg_get_serial_sequence(:t, 'id'), "
                        "COALESCE((SELECT MAX(id) FROM " + table_name + "), 1))"
                    ),
                    {"t": table_name},
                )

        if "alembic_version" in sq_tables:
            alem_rows = sq.execute("SELECT version_num FROM alembic_version").fetchall()
            if alem_rows:
                ver = alem_rows[0][0]
                conn.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS alembic_version ("
                        "version_num VARCHAR(32) NOT NULL, "
                        "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
                    )
                )
                conn.execute(text("DELETE FROM alembic_version"))
                conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": ver})
                print(f"[ALEMBIC] Stamped alembic_version to '{ver}'.")

    sq.close()
    print("SQLite -> PostgreSQL migration completed cleanly.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate Galley Control SQLite DB to PostgreSQL")
    parser.add_argument("--sqlite", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "galley_control.db"), help="Path to source galley_control.db")
    parser.add_argument(
        "--postgres-url",
        default=os.getenv("DATABASE_URL_UNPOOLED") or os.getenv("DATABASE_URL") or "",
        help="Target PostgreSQL DATABASE_URL (defaults to DATABASE_URL_UNPOOLED or DATABASE_URL)",
    )
    args = parser.parse_args()
    if not args.postgres_url:
        raise SystemExit("Error: Target PostgreSQL URL is missing. Set DATABASE_URL_UNPOOLED / DATABASE_URL or pass --postgres-url.")
    migrate_sqlite_to_postgres(args.sqlite, args.postgres_url)


if __name__ == "__main__":
    main()
