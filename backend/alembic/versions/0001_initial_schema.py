"""Initial relational schema for Galley Control (PostgreSQL & SQLite compatible).

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-25 20:40:00
"""

from __future__ import annotations

from alembic import op
from app.database import _sync_missing_columns
from app.models import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    _sync_missing_columns(bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, checkfirst=True)
