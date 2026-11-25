"""Add multi-tenant organisations table and non-destructive organisation_id isolation backfill.

Revision ID: 0002_multi_tenant_organisations
Revises: 0001_initial_schema
Create Date: 2026-11-25 21:40:00
"""

from __future__ import annotations

from alembic import op
from app.database import _sync_missing_columns
from app.models import Base

revision = "0002_multi_tenant_organisations"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    _sync_missing_columns(bind)


def downgrade() -> None:
    # Intentionally non-destructive on multi-tenant columns in production
    pass
