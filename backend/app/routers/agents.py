"""Central Orchestrator conversational assistant, history, and tenant-isolated streaming routes."""

from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.agents.orchestrator import orchestrate_chat_stream, orchestrate_student_assistant
from app.config import settings
from app.database import db_session, get_db
from app.models import AiConversation, AiMessage, Outlet
from app.services.auth_service import get_current_user
from app.services.rate_limit import check_and_increment_rate_limit

router = APIRouter(prefix="/api/agents", tags=["agents"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1500)
    outlet_id: int | None = None
    organisation_id: int | None = None
    student_name: str = "User"
    conversation_id: int | None = None


def _validate_tenant_request_params(
    db: Session,
    payload: ChatRequest,
    current_user: dict,
) -> None:
    """Reject cross-tenant organisation_id or outlet_id probing in chatbot calls."""
    if current_user["role"] == "admin":
        return
    user_org_id = current_user.get("organisation_id")
    if payload.organisation_id is not None and payload.organisation_id != user_org_id:
        raise HTTPException(
            status_code=403,
            detail="Access denied: cannot query chatbot data for another organisation.",
        )
    if payload.outlet_id is not None:
        outlet = db.execute(select(Outlet).where(Outlet.id == payload.outlet_id)).scalar_one_or_none()
        if outlet and outlet.organisation_id != user_org_id:
            raise HTTPException(
                status_code=403,
                detail="Access denied: requested outlet belongs to another organisation.",
            )


@router.get("/conversations")
def list_conversations(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List saved AI assistant conversations belonging strictly to the logged-in user and tenant."""
    stmt = select(AiConversation).where(AiConversation.user_id == current_user["id"])
    if current_user["role"] != "admin":
        stmt = stmt.where(AiConversation.organisation_id == current_user.get("organisation_id"))
    rows = db.execute(
        stmt.order_by(AiConversation.updated_at.desc(), AiConversation.id.desc()).limit(25)
    ).scalars().all()
    return {
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "role_context": c.role_context,
                "organisation_id": c.organisation_id,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in rows
        ]
    }


@router.get("/conversations/{conversation_id}")
def get_conversation_messages(
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetch full turn-by-turn history of one user-owned conversation within tenant boundary."""
    stmt = select(AiConversation).where(
        AiConversation.id == conversation_id,
        AiConversation.user_id == current_user["id"],
    )
    if current_user["role"] != "admin":
        stmt = stmt.where(AiConversation.organisation_id == current_user.get("organisation_id"))
    conv = db.execute(stmt).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    msgs = db.execute(
        select(AiMessage)
        .where(AiMessage.conversation_id == conv.id)
        .order_by(AiMessage.id.asc())
    ).scalars().all()

    return {
        "conversation": {"id": conv.id, "title": conv.title, "role_context": conv.role_context},
        "messages": [
            {
                "id": m.id,
                "sender": m.sender,
                "content": m.content,
                "ai_mode": m.ai_mode,
                "agents_invoked": json.loads(m.agents_invoked_json)
                if m.agents_invoked_json
                else [],
                "metadata": json.loads(m.metadata_json) if m.metadata_json else {},
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in msgs
        ],
    }


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a saved user-owned AI conversation."""
    stmt = select(AiConversation).where(
        AiConversation.id == conversation_id,
        AiConversation.user_id == current_user["id"],
    )
    if current_user["role"] != "admin":
        stmt = stmt.where(AiConversation.organisation_id == current_user.get("organisation_id"))
    conv = db.execute(stmt).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    db.execute(delete(AiConversation).where(AiConversation.id == conv.id))
    return {"status": "deleted", "conversation_id": conversation_id}


@router.post("/chat")
def chat_with_orchestrator(
    payload: ChatRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Multi-turn, strictly tenant-isolated AI assistant routed via Central Orchestrator."""
    _validate_tenant_request_params(db, payload, current_user)
    check_and_increment_rate_limit(
        db,
        bucket_key=f"chat_user:{current_user['id']}",
        max_attempts=settings.chat_rate_limit_per_min,
        window_seconds=60,
        block_seconds=60,
        error_message="Chat rate limit exceeded.",
    )
    return orchestrate_student_assistant(
        db,
        payload.message,
        payload.outlet_id,
        current_user["full_name"] or payload.student_name,
        current_user=current_user,
        conversation_id=payload.conversation_id,
        admin_organisation_id=payload.organisation_id if current_user["role"] == "admin" else None,
    )


@router.post("/chat/stream")
def stream_chat_with_orchestrator(
    payload: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """SSE streaming endpoint strictly isolated to caller's server-derived organisation & role."""
    with db_session() as db:
        _validate_tenant_request_params(db, payload, current_user)
        check_and_increment_rate_limit(
            db,
            bucket_key=f"chat_user:{current_user['id']}",
            max_attempts=settings.chat_rate_limit_per_min,
            window_seconds=60,
            block_seconds=60,
            error_message="Chat rate limit exceeded.",
        )
    return StreamingResponse(
        orchestrate_chat_stream(
            payload.message,
            payload.outlet_id,
            current_user=current_user,
            conversation_id=payload.conversation_id,
            admin_organisation_id=payload.organisation_id if current_user["role"] == "admin" else None,
        ),
        media_type="text/event-stream",
    )
