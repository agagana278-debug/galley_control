"""Pytest configuration and global isolation fixtures.

Guarantees tests always execute in isolated local SQLite environments
and never accidentally connect to the remote production/Neon database.
"""

import pytest
from app.config import settings


@pytest.fixture(autouse=True)
def isolate_test_database(monkeypatch):
    """Enforce isolated database configuration for all test runs."""
    # When testing, default to empty database_url so tests use their local test sqlite path
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "database_url_unpooled", "")
