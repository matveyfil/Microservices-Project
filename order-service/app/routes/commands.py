"""
Command Routes - Write side of CQRS

These routes handle state-changing operations:
POST   /orders          - place a new order (triggers Saga)
PATCH  /orders/{id}     - update order status (kitchen/waiter updates)
DELETE /orders/{id}     - cancel an order
"""

import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.database import get_db
from app.models import Order, OutboxEvent
from app.schemas import CreateOrderRequest, UpdateOrderStatusRequest, OrderResponse
from app.saga import place_order_saga

router = APIRouter()

# Valid status transitions - prevents invalid state changes
ALLOWED_TRANSITIONS = {
    "CONFIRMED": ["IN_PREPARATION"],
    "IN_PREPARATION": ["READY", "ON_HOLD"],
    "ON_HOLD": ["IN_PREPARATION", "CANCELLED"],
    "READY": ["SERVED"],
    "SERVED": ["PAID"],
    "PAID": ["CLOSED"],
}


@router.post("/orders", response_model=OrderResponse)
async def place_order(request: CreateOrderRequest, db: AsyncSession = Depends(get_db)):
    """
    Place a new order. This triggers the Order Placement Saga:
    1. Create order (PENDING)
    2. Reserve inventory
    3. Create bill
    4. Confirm order (CONFIRMED) or cancel with compensation
    """
    # Calculate total from items
    total = sum(item.price * item.quantity for item in request.items)

    # Step 1 of Saga: Create order in PENDING state
    # Generate UUID here explicitly - SQLAlchemy only applies column defaults at flush time,
    # so order.id would be None if we relied on the model default
    order_id = str(uuid.uuid4())
    order = Order(
        id=order_id,
        table_id=request.table_id,
        customer_name=request.customer_name,
        items=[item.model_dump() for item in request.items],
        total_amount=total,
        status="PENDING"
    )
    db.add(order)

    # Write outbox event atomically with the order creation
    outbox_event = OutboxEvent(
        event_type="ORDER_CREATED",
        payload={
            "order_id": order_id,
            "table_id": order.table_id,
            "customer_name": order.customer_name,
            "items": order.items,
            "total_amount": float(total)
        }
    )
    db.add(outbox_event)
    await db.commit()
    await db.refresh(order)

    # Run saga (steps 2-4): reserve inventory → create bill → confirm
    result = await place_order_saga(order, db)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    await db.refresh(order)
    return order


@router.patch("/orders/{order_id}", response_model=OrderResponse)
async def update_order_status(
    order_id: str,
    request: UpdateOrderStatusRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Update order status. Used by kitchen staff and waiters.
    Validates that the transition is allowed.
    """
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Check if transition is valid
    allowed = ALLOWED_TRANSITIONS.get(order.status, [])
    if request.status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from {order.status} to {request.status}. Allowed: {allowed}"
        )

    order.status = request.status
    order.updated_at = datetime.utcnow()

    # Write outbox event atomically
    outbox_event = OutboxEvent(
        event_type="ORDER_STATUS_UPDATED",
        payload={
            "order_id": order.id,
            "table_id": order.table_id,
            "status": request.status
        }
    )
    db.add(outbox_event)
    await db.commit()
    await db.refresh(order)
    return order


@router.delete("/orders/{order_id}", response_model=OrderResponse)
async def cancel_order(order_id: str, db: AsyncSession = Depends(get_db)):
    """Cancel an order. Only allowed before IN_PREPARATION."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status in ("IN_PREPARATION", "READY", "SERVED", "PAID", "CLOSED"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel order in status {order.status}. Requires manager approval."
        )

    order.status = "CANCELLED"
    order.updated_at = datetime.utcnow()

    outbox_event = OutboxEvent(
        event_type="ORDER_CANCELLED",
        payload={"order_id": order.id, "table_id": order.table_id, "status": "CANCELLED"}
    )
    db.add(outbox_event)
    await db.commit()
    await db.refresh(order)
    return order
