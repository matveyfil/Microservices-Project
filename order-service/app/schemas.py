from pydantic import BaseModel, Field
from typing import List
from datetime import datetime


# ─── Request schemas (what the client sends) ───────────────────────────────────

class OrderItem(BaseModel):
    name: str
    quantity: int = Field(gt=0)         # must be greater than 0
    price: float = Field(gt=0)          # must be greater than 0


class CreateOrderRequest(BaseModel):
    table_id: str
    customer_name: str
    items: List[OrderItem] = Field(min_length=1)   # at least one item required


class UpdateOrderStatusRequest(BaseModel):
    status: str
    # Allowed transitions:
    # IN_PREPARATION → READY (kitchen marks dish ready)
    # READY → SERVED (waiter delivers dish)
    # SERVED → PAID (payment processed)


# ─── Response schemas (what we send back) ──────────────────────────────────────

class OrderResponse(BaseModel):
    id: str
    table_id: str
    customer_name: str
    items: list
    total_amount: float
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KitchenOrderView(BaseModel):
    """
    Optimised read model for kitchen staff.
    Only contains what kitchen needs to see.
    This is the CQRS read projection.
    """
    id: str
    table_id: str
    items: list
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
