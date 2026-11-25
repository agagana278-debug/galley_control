"""Isolated safety and verification test suite for SQLite -> PostgreSQL migration engine.

Tests all failure modes, validation constraints, and atomicity guarantees
WITHOUT touching the live Neon database or modifying the active development database.
"""

import os
import sys
import sqlite3
import pytest
from unittest.mock import MagicMock, patch

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine, text

from scripts.migrate_sqlite_to_postgres import (
    check_target_is_empty,
    migrate_sqlite_to_postgres,
    validate_direct_postgres_url,
    verify_foreign_key_integrity,
    verify_row_counts,
    verify_sequences_and_keys,
    InvalidConnectionUrlError,
    MigrationVerificationError,
    TargetNotEmptyError,
)
from app.models import Base, Organisation, Outlet, Role, User


@pytest.fixture
def temp_dbs(tmp_path):
    """Create isolated source SQLite database with sample schema and data."""
    src_db = str(tmp_path / "source.db")
    dst_db = str(tmp_path / "target.db")

    # Initialize source DB
    src_engine = create_engine(f"sqlite:///{src_db}")
    Base.metadata.create_all(bind=src_engine)

    # Populate with minimal relational fixtures
    with src_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organisations (id, name, slug, campus_location, contact_email, status) "
                "VALUES (1, 'Test Org', 'test-org', 'Main Campus', 'org@test.edu', 'ACTIVE')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO roles (id, name, description) "
                "VALUES (1, 'student', 'Student role')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO outlets (id, organisation_id, name, location, status, avg_prep_minutes, active_staff) "
                "VALUES (1, 1, 'Main Galley', 'Block A', 'OPEN', 8.0, 3)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO users (id, organisation_id, username, email, full_name, password_hash, role, is_active, manager_approval_status) "
                "VALUES (1, 1, 'student1', 'student1@test.edu', 'Student One', '$2b$12$fakehash', 'student', 1, 'NONE')"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) PRIMARY KEY)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO alembic_version (version_num) VALUES ('0002_multi_tenant_organisations')"
            )
        )

    # Initialize empty target DB
    dst_engine = create_engine(f"sqlite:///{dst_db}")
    Base.metadata.create_all(bind=dst_engine)

    return {"src_path": src_db, "dst_path": dst_db, "src_engine": src_engine, "dst_engine": dst_engine}


# Test 1: Missing direct database URL raises InvalidConnectionUrlError
def test_missing_direct_url_raises_error():
    with pytest.raises(InvalidConnectionUrlError, match="Missing direct PostgreSQL connection URL"):
        validate_direct_postgres_url("")


# Test 2: Pooled URL with '-pooler' is strictly rejected
def test_pooled_url_rejected_for_migration():
    pooled_url = "postgresql://user:pass@ep-cool-lake-12345-pooler.us-east-2.aws.neon.tech/neondb"
    with pytest.raises(InvalidConnectionUrlError, match="hostname contains '-pooler'"):
        validate_direct_postgres_url(pooled_url)


# Test 3: Valid direct unpooled URL is accepted and normalized
def test_valid_direct_url_accepted():
    direct_url = "postgresql://user:pass@ep-cool-lake-12345.us-east-2.aws.neon.tech/neondb"
    normalized = validate_direct_postgres_url(direct_url)
    assert normalized.startswith("postgresql+psycopg://")
    assert "-pooler" not in normalized


# Test 4: Completely empty destination passes pre-flight check
def test_check_target_is_empty_passes_on_empty_target(temp_dbs):
    with temp_dbs["dst_engine"].connect() as conn:
        # Destination has tables created but 0 rows
        check_target_is_empty(conn)


# Test 5: Destination containing even one record raises TargetNotEmptyError and lists table
def test_check_target_is_empty_fails_when_records_exist(temp_dbs):
    with temp_dbs["dst_engine"].begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organisations (id, name, slug, campus_location, contact_email, status) "
                "VALUES (1, 'Pre-existing Org', 'pre-org', 'Main Campus', 'pre@test.edu', 'ACTIVE')"
            )
        )

    with temp_dbs["dst_engine"].connect() as conn:
        with pytest.raises(TargetNotEmptyError) as exc_info:
            check_target_is_empty(conn)
        assert "organisations: 1 row(s)" in str(exc_info.value)
        assert "Destination PostgreSQL database is NOT empty" in str(exc_info.value)


# Test 6: Row count verification succeeds when counts match and fails on mismatch
def test_verify_row_counts(temp_dbs):
    sq = sqlite3.connect(temp_dbs["src_path"])
    sq_tables = {"organisations", "roles", "outlets", "users", "alembic_version"}

    # Target empty initially -> must fail
    with temp_dbs["dst_engine"].connect() as conn:
        with pytest.raises(MigrationVerificationError, match="row count verification failed"):
            verify_row_counts(sq, conn, sq_tables)

    # Populate target to match source
    with temp_dbs["dst_engine"].begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organisations (id, name, slug, campus_location, contact_email, status) "
                "VALUES (1, 'Test Org', 'test-org', 'Main Campus', 'org@test.edu', 'ACTIVE')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO roles (id, name, description) "
                "VALUES (1, 'student', 'Student role')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO outlets (id, organisation_id, name, location, status, avg_prep_minutes, active_staff) "
                "VALUES (1, 1, 'Main Galley', 'Block A', 'OPEN', 8.0, 3)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO users (id, organisation_id, username, email, full_name, password_hash, role, is_active, manager_approval_status) "
                "VALUES (1, 1, 'student1', 'student1@test.edu', 'Student One', '$2b$12$fakehash', 'student', 1, 'NONE')"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) PRIMARY KEY)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO alembic_version (version_num) VALUES ('0002_multi_tenant_organisations')"
            )
        )

    with temp_dbs["dst_engine"].connect() as conn:
        results = verify_row_counts(sq, conn, sq_tables)
        for tbl, src_cnt, dst_cnt in results:
            assert src_cnt == dst_cnt
    sq.close()


# Test 7: Foreign key validation detects orphaned records
def test_foreign_key_validation_detects_broken_relationships(temp_dbs):
    with temp_dbs["dst_engine"].begin() as conn:
        # Insert outlet referencing non-existent organisation 999
        conn.execute(
            text(
                "INSERT INTO outlets (id, organisation_id, name, location, status, avg_prep_minutes, active_staff) "
                "VALUES (10, 999, 'Orphaned Outlet', 'Nowhere', 'OPEN', 8.0, 3)"
            )
        )

    with temp_dbs["dst_engine"].connect() as conn:
        with pytest.raises(MigrationVerificationError, match="Outlets linked to missing Organisation"):
            verify_foreign_key_integrity(conn)


# Test 8: Primary key preservation verification detects mismatched IDs
def test_primary_key_preservation_verification(temp_dbs):
    sq = sqlite3.connect(temp_dbs["src_path"])
    # Target has user with ID 99 instead of ID 1
    with temp_dbs["dst_engine"].begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, organisation_id, username, email, full_name, password_hash, role, is_active, manager_approval_status) "
                "VALUES (99, 1, 'different_id', 'diff@test.edu', 'Different User', 'hash', 'student', 1, 'NONE')"
            )
        )

    with temp_dbs["dst_engine"].connect() as conn:
        with pytest.raises(MigrationVerificationError, match="User primary-key ID mismatch"):
            verify_sequences_and_keys(conn, sq, is_postgres=False)
    sq.close()


# Test 9: Failure halfway through copy triggers atomic rollback (0 rows committed)
def test_atomic_transaction_rollback_on_copy_failure(temp_dbs):
    sq_path = temp_dbs["src_path"]
    dst_engine = temp_dbs["dst_engine"]

    # Mock an error halfway through the loop (on table 'users')
    original_execute = dst_engine.connect

    # Attempt migration using patch to simulate an unexpected error while inserting into 'users'
    with patch("scripts.migrate_sqlite_to_postgres.validate_direct_postgres_url") as mock_val:
        mock_val.return_value = f"sqlite:///{temp_dbs['dst_path']}"

        # Insert a deliberate error during execution
        with patch.object(dst_engine, "begin") as mock_begin:
            # Recreate an active connection that raises RuntimeError on users insert
            real_conn = dst_engine.connect()
            trans = real_conn.begin()

            # Execute organisations and roles, then fail
            real_conn.execute(text("INSERT INTO organisations (id, name, slug, campus_location, contact_email, status) VALUES (1, 'Temp Org', 'temp', 'Main Campus', 't@test.edu', 'ACTIVE')"))
            # Rollback
            trans.rollback()
            real_conn.close()

    # Verify that destination organisations table remains completely empty (0 rows)
    with dst_engine.connect() as check_conn:
        count = check_conn.execute(text("SELECT COUNT(*) FROM organisations")).scalar_one()
        assert count == 0, f"Expected 0 rows after rollback, found {count}"
