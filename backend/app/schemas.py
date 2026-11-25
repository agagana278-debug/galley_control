"""Pydantic request and response schemas for Galley Control."""

from typing import Optional
from pydantic import BaseModel, Field


class OrderItemInput(BaseModel):
    menu_item_id: int
    quantity: int = Field(ge=1, le=20)


class OrderCreateRequest(BaseModel):
    outlet_id: int
    student_name: str = Field(min_length=1, max_length=80)
    items: list[OrderItemInput] = Field(min_length=1)
    group_code: Optional[str] = Field(default=None, max_length=32)
    scheduled_slot: Optional[str] = Field(default=None, max_length=20)
    simulate_payment_success: bool = True


class QRVerifyRequest(BaseModel):
    token: str = Field(min_length=4, max_length=120)


class RefundRequest(BaseModel):
    reason: str = Field(default="Student requested cancellation", min_length=3, max_length=300)


class ReviewCreateRequest(BaseModel):
    outlet_id: int
    order_id: Optional[int] = None
    student_name: str = Field(min_length=1, max_length=80)
    rating: int = Field(ge=1, le=5)
    comment: str = Field(min_length=3, max_length=500)


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    outlet_id: Optional[int] = None
    student_name: str = "Student"


class RecommendationActionRequest(BaseModel):
    status: str = Field(pattern="^(APPROVED|DISMISSED)$")
