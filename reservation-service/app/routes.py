from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from pydantic import BaseModel, Field
from typing import List
from datetime import datetime

from app.database import get_db
from app.models import Table, Reservation, OutboxEvent

router = APIRouter()


# ─── Request schemas ────────────────────────────────────────────────────────────

class CreateTableRequest(BaseModel):
    number: str          # e.g. "T1"
    capacity: int = Field(gt=0)


class CreateReservationRequest(BaseModel):
    table_id: str
    customer_name: str
    party_size: int = Field(gt=0)
    time_slot: str       # e.g. "2024-01-15 19:00"


# ─── Table management ───────────────────────────────────────────────────────────

@router.post("/tables")
async def create_table(request: CreateTableRequest, db: AsyncSession = Depends(get_db)):
    """Add a new table to the restaurant."""
    table = Table(number=request.number, capacity=request.capacity)
    db.add(table)
    await db.commit()
    await db.refresh(table)
    return table


@router.get("/tables")
async def get_tables(db: AsyncSession = Depends(get_db)):
    """Get all tables and their current status."""
    result = await db.execute(select(Table))
    return result.scalars().all()


# ─── Reservation management ─────────────────────────────────────────────────────

@router.post("/reservations")
async def create_reservation(request: CreateReservationRequest, db: AsyncSession = Depends(get_db)):
    """
    Request a reservation.
    Checks that:
    1. Table exists and has enough capacity for the party
    2. Table is not already booked for that time slot
    Prevents double-booking.
    """
    # Check table exists
    result = await db.execute(select(Table).where(Table.id == request.table_id))
    table = result.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    # Check capacity
    if table.capacity < request.party_size:
        raise HTTPException(
            status_code=400,
            detail=f"Table {table.number} capacity is {table.capacity}, party size is {request.party_size}"
        )

    # Check no conflicting reservation exists for same table + time slot
    conflict_result = await db.execute(
        select(Reservation).where(
            and_(
                Reservation.table_id == request.table_id,
                Reservation.time_slot == request.time_slot,
                Reservation.status.in_(["REQUESTED", "CONFIRMED", "ACTIVE"])
            )
        )
    )
    if conflict_result.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail=f"Table {table.number} is already booked for {request.time_slot}"
        )

    reservation = Reservation(
        table_id=request.table_id,
        customer_name=request.customer_name,
        party_size=request.party_size,
        time_slot=request.time_slot,
        status="REQUESTED"
    )
    db.add(reservation)

    outbox_event = OutboxEvent(
        event_type="RESERVATION_REQUESTED",
        payload={
            "reservation_id": reservation.id,
            "table_id": reservation.table_id,
            "customer_name": reservation.customer_name,
            "time_slot": reservation.time_slot
        }
    )
    db.add(outbox_event)
    await db.commit()
    await db.refresh(reservation)
    return reservation


@router.get("/reservations")
async def get_reservations(db: AsyncSession = Depends(get_db)):
    """Get all reservations."""
    result = await db.execute(select(Reservation).order_by(Reservation.created_at.desc()))
    return result.scalars().all()


@router.patch("/reservations/{reservation_id}/confirm")
async def confirm_reservation(reservation_id: str, db: AsyncSession = Depends(get_db)):
    """Host confirms the reservation (REQUESTED → CONFIRMED)."""
    result = await db.execute(select(Reservation).where(Reservation.id == reservation_id))
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")
    if reservation.status != "REQUESTED":
        raise HTTPException(status_code=400, detail=f"Cannot confirm reservation in status {reservation.status}")

    reservation.status = "CONFIRMED"
    reservation.updated_at = datetime.utcnow()

    outbox_event = OutboxEvent(
        event_type="RESERVATION_CONFIRMED",
        payload={"reservation_id": reservation.id, "table_id": reservation.table_id}
    )
    db.add(outbox_event)
    await db.commit()
    await db.refresh(reservation)
    return reservation


@router.patch("/reservations/{reservation_id}/seat")
async def seat_customer(reservation_id: str, db: AsyncSession = Depends(get_db)):
    """Customer arrives - mark reservation ACTIVE and table OCCUPIED (CONFIRMED → ACTIVE)."""
    result = await db.execute(select(Reservation).where(Reservation.id == reservation_id))
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")
    if reservation.status != "CONFIRMED":
        raise HTTPException(status_code=400, detail="Reservation must be CONFIRMED before seating")

    reservation.status = "ACTIVE"
    reservation.updated_at = datetime.utcnow()

    # Mark table as occupied
    table_result = await db.execute(select(Table).where(Table.id == reservation.table_id))
    table = table_result.scalar_one_or_none()
    if table:
        table.status = "OCCUPIED"

    outbox_event = OutboxEvent(
        event_type="TABLE_SEATED",
        payload={"reservation_id": reservation.id, "table_id": reservation.table_id}
    )
    db.add(outbox_event)
    await db.commit()
    await db.refresh(reservation)
    return reservation


@router.patch("/reservations/{reservation_id}/complete")
async def complete_reservation(reservation_id: str, db: AsyncSession = Depends(get_db)):
    """Mark reservation complete and free the table (ACTIVE → COMPLETED)."""
    result = await db.execute(select(Reservation).where(Reservation.id == reservation_id))
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    reservation.status = "COMPLETED"
    reservation.updated_at = datetime.utcnow()

    table_result = await db.execute(select(Table).where(Table.id == reservation.table_id))
    table = table_result.scalar_one_or_none()
    if table:
        table.status = "AVAILABLE"

    outbox_event = OutboxEvent(
        event_type="RESERVATION_COMPLETED",
        payload={"reservation_id": reservation.id, "table_id": reservation.table_id}
    )
    db.add(outbox_event)
    await db.commit()
    await db.refresh(reservation)
    return reservation


@router.patch("/reservations/{reservation_id}/cancel")
async def cancel_reservation(reservation_id: str, db: AsyncSession = Depends(get_db)):
    """Cancel a reservation and free the table if it was occupied."""
    result = await db.execute(select(Reservation).where(Reservation.id == reservation_id))
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    reservation.status = "CANCELLED"
    reservation.updated_at = datetime.utcnow()

    table_result = await db.execute(select(Table).where(Table.id == reservation.table_id))
    table = table_result.scalar_one_or_none()
    if table:
        table.status = "AVAILABLE"

    outbox_event = OutboxEvent(
        event_type="RESERVATION_CANCELLED",
        payload={"reservation_id": reservation.id, "table_id": reservation.table_id}
    )
    db.add(outbox_event)
    await db.commit()
    await db.refresh(reservation)
    return reservation
