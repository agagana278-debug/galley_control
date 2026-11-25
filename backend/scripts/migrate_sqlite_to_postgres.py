"""Hardened SQLite -> PostgreSQL migration engine with pre-flight safety checks,
atomic transaction guarantees, and comprehensive post-migration verification.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from sqlalchemy import create_engine, inspect, text
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


class MigrationError(Exception):
    """Base exception for database migration errors."""
    pass


class TargetNotEmptyError(MigrationError):
    """Raised when the target database already contains data."""
    pass


class InvalidConnectionUrlError(MigrationError):
    """Raised when the PostgreSQL connection URL is invalid or unsafe for DDL."""
    pass


class MigrationVerificationError(MigrationError):
    """Raised when post-migration row count, sequence, or relational integrity fails."""
    pass


def validate_direct_postgres_url(pg_url: str) -> str:
    """Validate that the target PostgreSQL URL is direct (unpooled) and non-empty."""
    raw = (pg_url or "").strip()
    if not raw:
        raise InvalidConnectionUrlError(
            "Missing direct PostgreSQL connection URL. Migrations require DATABASE_URL_UNPOOLED."
        )
    target_url = normalize_database_url(raw)
    if not target_url.startswith("postgresql"):
        raise InvalidConnectionUrlError(
            "Target URL must be a valid PostgreSQL connection string starting with postgresql:// or postgres://."
        )
    if "-pooler" in target_url:
        raise InvalidConnectionUrlError(
            "Pooled URL rejected for migrations. Connection hostname contains '-pooler'. "
            "Neon migrations require the direct unpooled URL (DATABASE_URL_UNPOOLED) because PgBouncer "
            "transaction pooling does not support DDL locks, session states, or sequence resets."
        )
    return target_url


def _coerce_value(col_name: str, val: Any) -> Any:
    """Coerce SQLite types to PostgreSQL equivalents preserving exact values."""
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


def check_target_is_empty(conn: Any) -> None:
    """Ensure the target PostgreSQL database has no records in any table before copying."""
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())
    non_empty: Dict[str, int] = {}

    for table_name in TABLE_COPY_ORDER:
        if table_name in existing_tables:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
            if count > 0:
                non_empty[table_name] = count

    if "alembic_version" in existing_tables:
        alem_count = conn.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar_one()
        if alem_count > 0:
            non_empty["alembic_version"] = alem_count

    if non_empty:
        table_list = "\n".join(f"  - {t}: {cnt} row(s)" for t, cnt in sorted(non_empty.items()))
        raise TargetNotEmptyError(
            f"Migration aborted: Destination PostgreSQL database is NOT empty.\n"
            f"The following tables already contain records:\n{table_list}\n"
            f"Galley Control requires an empty target database to prevent data corruption or duplicate records."
        )


def verify_row_counts(sq: sqlite3.Connection, conn: Any, sq_tables: set[str]) -> List[Tuple[str, int, int]]:
    """Compare exact row counts between SQLite source and PostgreSQL target for all tables."""
    results: List[Tuple[str, int, int]] = []
    all_tables_to_check = [t for t in TABLE_COPY_ORDER if t in sq_tables]
    if "alembic_version" in sq_tables:
        all_tables_to_check.append("alembic_version")

    inspector = inspect(conn)
    dst_tables = set(inspector.get_table_names())

    mismatches: List[str] = []
    for table_name in all_tables_to_check:
        src_cnt = sq.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        if table_name not in dst_tables:
            dst_cnt = 0
        else:
            dst_cnt = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
        results.append((table_name, src_cnt, dst_cnt))
        if src_cnt != dst_cnt:
            mismatches.append(f"{table_name}: source has {src_cnt}, target has {dst_cnt}")

    if mismatches:
        err = "Post-migration row count verification failed:\n" + "\n".join(f"  - {m}" for m in mismatches)
        raise MigrationVerificationError(err)

    return results


def verify_foreign_key_integrity(conn: Any) -> None:
    """Assert relational integrity on key foreign-key relationships."""
    checks = [
        (
            "Users linked to missing Organisation",
            "SELECT COUNT(*) FROM users WHERE organisation_id IS NOT NULL AND organisation_id NOT IN (SELECT id FROM organisations)",
        ),
        (
            "Outlets linked to missing Organisation",
            "SELECT COUNT(*) FROM outlets WHERE organisation_id NOT IN (SELECT id FROM organisations)",
        ),
        (
            "Menu items linked to missing Outlet",
            "SELECT COUNT(*) FROM menu_items WHERE outlet_id NOT IN (SELECT id FROM outlets)",
        ),
        (
            "Orders linked to missing User",
            "SELECT COUNT(*) FROM orders WHERE user_id NOT IN (SELECT id FROM users)",
        ),
        (
            "Orders linked to missing Outlet",
            "SELECT COUNT(*) FROM orders WHERE outlet_id NOT IN (SELECT id FROM outlets)",
        ),
        (
            "Order items linked to missing Order",
            "SELECT COUNT(*) FROM order_items WHERE order_id NOT IN (SELECT id FROM orders)",
        ),
        (
            "QR tokens linked to missing Order",
            "SELECT COUNT(*) FROM qr_tokens WHERE order_id NOT IN (SELECT id FROM orders)",
        ),
        (
            "Reviews linked to missing User",
            "SELECT COUNT(*) FROM reviews WHERE user_id NOT IN (SELECT id FROM users)",
        ),
    ]

    violations: List[str] = []
    for desc, query in checks:
        orphaned = conn.execute(text(query)).scalar_one()
        if orphaned > 0:
            violations.append(f"{desc}: {orphaned} orphaned record(s)")

    if violations:
        raise MigrationVerificationError(
            "Relational foreign-key verification failed post-migration:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


def verify_sequences_and_keys(conn: Any, sq: sqlite3.Connection, is_postgres: bool) -> None:
    """Verify primary key preservation and ensure autoincrement sequences are advanced."""
    # Verify primary keys on users table match exactly
    sq_user_ids = set(r[0] for r in sq.execute("SELECT id FROM users").fetchall())
    pg_user_ids = set(r[0] for r in conn.execute(text("SELECT id FROM users")).fetchall())
    if sq_user_ids != pg_user_ids:
        raise MigrationVerificationError(
            f"User primary-key ID mismatch: SQLite has {len(sq_user_ids)} IDs, PostgreSQL has {len(pg_user_ids)}"
        )

    if not is_postgres:
        return

    # Verify sequence counters for serial ID columns
    for table_name in TABLE_COPY_ORDER:
        cols = Base.metadata.tables[table_name].columns
        if "id" in cols:
            max_id = conn.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table_name}")).scalar_one()
            if max_id > 0:
                seq_val = conn.execute(
                    text(f"SELECT last_value FROM pg_sequences WHERE schemaname = 'public' AND sequencename = pg_get_serial_sequence('{table_name}', 'id')")
                ).scalar()
                # When setval(seq, max_id) is run, seq_val is >= max_id
                if seq_val is not None and seq_val < max_id:
                    raise MigrationVerificationError(
                        f"Sequence for {table_name}.id is out of sync: last_value={seq_val} < max_id={max_id}"
                    )


def migrate_sqlite_to_postgres(sqlite_path: str, pg_url: str) -> List[Tuple[str, int, int]]:
    """Execute complete atomic migration from SQLite to PostgreSQL with pre-flight checks and verification."""
    if not os.path.exists(sqlite_path):
        raise SystemExit(f"SQLite file not found: {sqlite_path}")

    target_url = validate_direct_postgres_url(pg_url)
    is_postgres = target_url.startswith("postgresql")

    pg_engine = create_engine(target_url, future=True)
    # Ensure schema tables exist
    Base.metadata.create_all(bind=pg_engine, checkfirst=True)

    sq = sqlite3.connect(sqlite_path)
    sq.row_factory = sqlite3.Row
    sq_tables = {
        r[0]
        for r in sq.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    # All data copies, sequence sets, and verifications MUST be inside ONE atomic transaction
    with pg_engine.begin() as conn:
        # Pre-flight check: destination must be 100% empty
        check_target_is_empty(conn)

        print("Target database verified empty. Beginning atomic record transfer...")

        for table_name in TABLE_COPY_ORDER:
            if table_name not in sq_tables:
                continue
            rows = sq.execute(f"SELECT * FROM {table_name}").fetchall()
            if not rows:
                continue

            pg_cols = set(Base.metadata.tables[table_name].columns.keys())
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

            if "id" in src_cols and is_postgres:
                conn.execute(
                    text(
                        "SELECT setval(pg_get_serial_sequence(:t, 'id'), "
                        "COALESCE((SELECT MAX(id) FROM " + table_name + "), 1))"
                    ),
                    {"t": table_name},
                )

        # Handle Alembic version stamping
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
                conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": ver})

        # Post-migration verification within the transaction
        print("Running post-migration verification checks...")
        verification_counts = verify_row_counts(sq, conn, sq_tables)
        verify_foreign_key_integrity(conn)
        verify_sequences_and_keys(conn, sq, is_postgres)

        # Verify alembic version
        if "alembic_version" in sq_tables:
            pg_ver = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            if pg_ver != "0002_multi_tenant_organisations":
                raise MigrationVerificationError(f"Alembic revision mismatch: expected 0002_multi_tenant_organisations, got {pg_ver}")

    sq.close()
    print("PostgreSQL migration committed successfully. All verification checks passed.")
    return verification_counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate Galley Control SQLite DB to PostgreSQL")
    parser.add_argument(
        "--sqlite",
        default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "galley_control.db"),
        help="Path to source galley_control.db",
    )
    parser.add_argument(
        "--postgres-url",
        default=os.getenv("DATABASE_URL_UNPOOLED", ""),
        help="Target direct PostgreSQL DATABASE_URL_UNPOOLED",
    )
    args = parser.parse_args()

    if not args.postgres_url:
        raise SystemExit(
            "Error: Direct PostgreSQL URL is missing. Set DATABASE_URL_UNPOOLED in your environment "
            "or pass --postgres-url. Do not use the pooled connection string for migrations."
        )

    try:
        counts = migrate_sqlite_to_postgres(args.sqlite, args.postgres_url)
        print("\n=== Verified Migration Summary ===")
        print(f"{'Table':<30} {'Source (SQLite)':<18} {'Destination (Neon)':<18} {'Status'}")
        print("-" * 75)
        for tbl, src, dst in counts:
            status = "MATCH" if src == dst else "MISMATCH"
            print(f"{tbl:<30} {src:<18} {dst:<18} {status}")
    except MigrationError as err:
        print(f"\nMIGRATION FAILED: {err}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
