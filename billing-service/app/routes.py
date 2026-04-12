import random
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import datetime

from app.database import get_db
from app.models import Bill, OutboxEvent

router = APIRouter()


# ─── Request schemas ────────────────────────────────────────────────────────────

class CreateBillRequest(BaseModel):
    order_id: str
    table_id: str
    total_amount: float


class ProcessPaymentRequest(BaseModel):
    order_id: str


# ─── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/bills")
async def create_bill(request: CreateBillRequest, db: AsyncSession = Depends(get_db)):
    """
    Called by order-service during Saga Step 3.
    Creates a bill for the confirmed order.
    Returns 400 if bill already exists for this order (idempotent).
    """
    # Check if bill already exists (idempotency)
    result = await db.execute(select(Bill).where(Bill.order_id == request.order_id))
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    bill = Bill(
        order_id=request.order_id,
        table_id=request.table_id,
        total_amount=request.total_amount,
        status="PENDING"
    )
    db.add(bill)

    outbox_event = OutboxEvent(
        event_type="BILL_CREATED",
        payload={
            "bill_id": bill.id,
            "order_id": bill.order_id,
            "table_id": bill.table_id,
            "total_amount": float(bill.total_amount)
        }
    )
    db.add(outbox_event)
    await db.commit()
    await db.refresh(bill)
    return bill


@router.get("/bills")
async def get_all_bills(db: AsyncSession = Depends(get_db)):
    """Get all bills."""
    result = await db.execute(select(Bill).order_by(Bill.created_at.desc()))
    return result.scalars().all()


@router.get("/bills/{order_id}")
async def get_bill_by_order(order_id: str, db: AsyncSession = Depends(get_db)):
    """Get bill for a specific order."""
    result = await db.execute(select(Bill).where(Bill.order_id == order_id))
    bill = result.scalar_one_or_none()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    return bill


@router.post("/bills/{order_id}/pay")
async def process_payment(order_id: str, db: AsyncSession = Depends(get_db)):
    """
    Process payment for an order.
    Simulates an external payment gateway - has a 20% chance of failure
    to demonstrate Saga failure handling.
    """
    result = await db.execute(select(Bill).where(Bill.order_id == order_id))
    bill = result.scalar_one_or_none()

    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")

    if bill.status == "PAID":
        return {"message": "Already paid", "bill": bill}

    # Simulate external payment gateway (80% success, 20% failure)
    payment_success = random.random() > 0.2

    if payment_success:
        bill.status = "PAID"
        bill.updated_at = datetime.utcnow()
        event_type = "PAYMENT_SUCCESS"
        message = "Payment processed successfully"
    else:
        bill.status = "FAILED"
        bill.updated_at = datetime.utcnow()
        event_type = "PAYMENT_FAILED"
        message = "Payment gateway failed. Please retry."

    outbox_event = OutboxEvent(
        event_type=event_type,
        payload={
            "bill_id": bill.id,
            "order_id": bill.order_id,
            "table_id": bill.table_id,
            "total_amount": float(bill.total_amount),
            "status": bill.status
        }
    )
    db.add(outbox_event)
    await db.commit()
    await db.refresh(bill)

    if not payment_success:
        raise HTTPException(status_code=400, detail=message)

    return {"message": message, "bill": bill}


@router.post("/bills/{order_id}/cancel")
async def cancel_bill(order_id: str, db: AsyncSession = Depends(get_db)):
    """
    Cancel a bill - Saga compensating action.
    Called when order is cancelled after bill was created.
    """
    result = await db.execute(select(Bill).where(Bill.order_id == order_id))
    bill = result.scalar_one_or_none()

    if not bill:
        return {"message": "Nothing to cancel"}

    if bill.status == "PAID":
        raise HTTPException(status_code=400, detail="Cannot cancel a paid bill. Requires manager approval for refund.")

    bill.status = "CANCELLED"
    bill.updated_at = datetime.utcnow()

    outbox_event = OutboxEvent(
        event_type="BILL_CANCELLED",
        payload={"bill_id": bill.id, "order_id": order_id}
    )
    db.add(outbox_event)
    await db.commit()

    return {"message": "Bill cancelled", "order_id": order_id}
