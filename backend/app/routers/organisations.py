"""Public organisation onboarding and active-tenant directory routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Organisation
from app.services.auth_service import register_organisation_with_manager

router = APIRouter(prefix="/api/organisations", tags=["organisations"])


class OrganisationRegisterRequest(BaseModel):
    org_name: str = Field(..., min_length=3, max_length=160)
    org_slug: str = Field(..., min_length=3, max_length=64)
    campus_location: str = Field(default="", max_length=160)
    contact_email: EmailStr
    manager_full_name: str = Field(..., min_length=2, max_length=100)
    manager_username: str = Field(..., min_length=3, max_length=32)
    manager_email: EmailStr
    password: str = Field(..., min_length=8, max_length=72)
    confirm_password: str = Field(..., min_length=8, max_length=72)


@router.get("/public")
def list_public_active_organisations(db: Session = Depends(get_db)) -> dict:
    """Return ONLY active approved campus organisations for public student sign-up."""
    rows = db.execute(
        select(Organisation)
        .where(Organisation.status == "ACTIVE")
        .order_by(Organisation.id.asc())
    ).scalars().all()
    return {
        "organisations": [
            {
                "id": o.id,
                "name": o.name,
                "slug": o.slug,
                "campus_location": o.campus_location,
            }
            for o in rows
        ]
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
def onboard_organisation(
    payload: OrganisationRegisterRequest,
    request: Request,
) -> dict:
    """Register a new college/canteen organisation for platform admin approval."""
    return register_organisation_with_manager(
        org_name=payload.org_name,
        org_slug=payload.org_slug,
        campus_location=payload.campus_location,
        contact_email=str(payload.contact_email),
        manager_full_name=payload.manager_full_name,
        manager_username=payload.manager_username,
        manager_email=str(payload.manager_email),
        password=payload.password,
        confirm_password=payload.confirm_password,
        request=request,
    )
