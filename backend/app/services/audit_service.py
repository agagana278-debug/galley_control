"""Persistent tenant-aware audit logging and AI agent activity tracking."""

from __future__ import annotations

import json
from typing import Any
from sqlalchemy.orm import Session

from app.models import AgentActivityLog, AuditLog


def record_audit_log(
    db: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: str | int | None = None,
    organisation_id: int | None = None,
    actor_user_id: int | None = None,
    actor_role: str | None = None,
    ip_address: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Write an immutable audit trail entry within the current transaction."""
    db.add(
        AuditLog(
            organisation_id=organisation_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            ip_address=ip_address,
            details_json=json.dumps(details, default=str) if details else None,
        )
    )


def record_agent_activity(
    db: Session,
    *,
    agent_name: str,
    orchestration_id: str,
    action_type: str,
    summary: str,
    organisation_id: int | None = None,
    user_id: int | None = None,
    outlet_id: int | None = None,
    data_source_type: str = "live_db",
) -> None:
    """Persist structured multi-agent telemetry to agent_activity_logs."""
    db.add(
        AgentActivityLog(
            organisation_id=organisation_id,
            agent_name=agent_name,
            orchestration_id=orchestration_id,
            user_id=user_id,
            outlet_id=outlet_id,
            action_type=action_type,
            summary=summary[:1000],
            data_source_type=data_source_type,
        )
    )
