from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import List
from datetime import datetime

from app.database import get_db
from app.models import Ingredient, InventoryReservation, OutboxEvent

router = APIRouter()


# ─── Request schemas ──────────────────────────────────────────────────────────────

class ReserveRequest(BaseModel):
    order_id: str
    items: List[dict]  # [{"name": "pasta", "quantity": 2}]


class ReleaseRequest(BaseModel):
    order_id: str


class AddIngredientRequest(BaseModel):
    name: str
    quantity: int
    unit: str
    threshold: int = 10


class RestockRequest(BaseModel):
    ingredient_name: str
    quantity: int


# ─── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/inventory")
async def get_all_ingredients(db: AsyncSession = Depends(get_db)):
    """View all ingredients and their stock levels."""
    result = await db.execute(select(Ingredient))
    return result.scalars().all()


@router.post("/inventory")
async def add_ingredient(request: AddIngredientRequest, db: AsyncSession = Depends(get_db)):
    """Add a new ingredient to inventory (used by operations manager)."""
    ingredient = Ingredient(
        name=request.name,
        quantity=request.quantity,
        unit=request.unit,
        threshold=request.threshold
    )
    db.add(ingredient)
    await db.commit()
    await db.refresh(ingredient)
    return ingredient


@router.post("/inventory/reserve")
async def reserve_inventory(request: ReserveRequest, db: AsyncSession = Depends(get_db)):
    """
    Called by order-service during Saga Step 2.
    Checks if all required ingredients are available and reserves them.
    This is atomic - either ALL ingredients are reserved or NONE.
    """
    # Check availability for all items first
    for item in request.items:
        result = await db.execute(
            select(Ingredient).where(Ingredient.name == item["name"])
        )
        ingredient = result.scalar_one_or_none()

        if not ingredient:
            raise HTTPException(
                status_code=400,
                detail=f"Ingredient '{item['name']}' not found in inventory"
            )

        if ingredient.quantity < item["quantity"]:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for '{item['name']}': "
                       f"need {item['quantity']}, have {ingredient.quantity}"
            )

    # All checks passed - now deduct stock
    for item in request.items:
        result = await db.execute(
            select(Ingredient).where(Ingredient.name == item["name"])
        )
        ingredient = result.scalar_one()
        ingredient.quantity -= item["quantity"]
        ingredient.updated_at = datetime.utcnow()

        # Check if we hit low stock threshold after deduction
        if ingredient.quantity <= ingredient.threshold:
            low_stock_event = OutboxEvent(
                event_type="INVENTORY_LOW_STOCK",
                payload={
                    "ingredient_name": ingredient.name,
                    "current_quantity": ingredient.quantity,
                    "threshold": ingredient.threshold,
                    "unit": ingredient.unit
                }
            )
            db.add(low_stock_event)
            print(f"[INVENTORY] LOW STOCK alert: {ingredient.name} = {ingredient.quantity} {ingredient.unit}")

    # Create reservation record
    reservation = InventoryReservation(
        order_id=request.order_id,
        reserved_items=request.items,
        status="RESERVED"
    )
    db.add(reservation)

    # Write outbox event atomically
    outbox_event = OutboxEvent(
        event_type="INVENTORY_RESERVED",
        payload={"order_id": request.order_id, "items": request.items}
    )
    db.add(outbox_event)

    await db.commit()
    return {"message": "Inventory reserved", "order_id": request.order_id}


@router.post("/inventory/release")
async def release_inventory(request: ReleaseRequest, db: AsyncSession = Depends(get_db)):
    """
    Saga compensating action - called when order is cancelled after inventory was reserved.
    Returns ingredients back to stock.
    """
    result = await db.execute(
        select(InventoryReservation)
        .where(InventoryReservation.order_id == request.order_id)
        .where(InventoryReservation.status == "RESERVED")
    )
    reservation = result.scalar_one_or_none()

    if not reservation:
        # Already released or doesn't exist - idempotent, return OK
        return {"message": "Nothing to release"}

    # Return stock
    for item in reservation.reserved_items:
        result = await db.execute(
            select(Ingredient).where(Ingredient.name == item["name"])
        )
        ingredient = result.scalar_one_or_none()
        if ingredient:
            ingredient.quantity += item["quantity"]
            ingredient.updated_at = datetime.utcnow()

    reservation.status = "RELEASED"

    outbox_event = OutboxEvent(
        event_type="INVENTORY_RELEASED",
        payload={"order_id": request.order_id}
    )
    db.add(outbox_event)
    await db.commit()

    print(f"[INVENTORY] Released stock for order {request.order_id}")
    return {"message": "Inventory released", "order_id": request.order_id}


@router.post("/inventory/restock")
async def restock_ingredient(request: RestockRequest, db: AsyncSession = Depends(get_db)):
    """Restock an ingredient (simulates supplier delivery)."""
    result = await db.execute(
        select(Ingredient).where(Ingredient.name == request.ingredient_name)
    )
    ingredient = result.scalar_one_or_none()

    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")

    ingredient.quantity += request.quantity
    ingredient.updated_at = datetime.utcnow()

    outbox_event = OutboxEvent(
        event_type="INVENTORY_RESTOCKED",
        payload={"ingredient_name": ingredient.name, "quantity_added": request.quantity}
    )
    db.add(outbox_event)
    await db.commit()

    return {"message": f"Restocked {request.ingredient_name} by {request.quantity}", "new_quantity": ingredient.quantity}
