"""
Order Placement Saga - Orchestration Pattern

This saga coordinates a multi-service transaction:
  Step 1: Create order in this service (status: PENDING)
  Step 2: Reserve ingredients in inventory-service
  Step 3: Create bill in billing-service
  Step 4: Confirm order (status: CONFIRMED)

If any step fails, we run compensating actions to undo previous steps.

Why orchestration (not choreography)?
- Order service is the natural owner of this workflow
- Easier to follow the logic - everything is in one place
- Easier to debug when something goes wrong
"""

import httpx
import os
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.models import Order, OutboxEvent

INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://localhost:8002")
BILLING_SERVICE_URL = os.getenv("BILLING_SERVICE_URL", "http://localhost:8003")


async def place_order_saga(order: Order, db: AsyncSession) -> dict:
    """
    Runs the full order placement saga.
    Returns {"success": True, "order": order} or {"success": False, "error": "..."}
    """

    # ── Step 2: Reserve ingredients in inventory-service ──────────────────────
    print(f"[SAGA] Step 2: Reserving inventory for order {order.id}")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            inventory_response = await client.post(
                f"{INVENTORY_SERVICE_URL}/inventory/reserve",
                json={
                    "order_id": order.id,
                    "items": order.items  # list of items with names and quantities
                }
            )

        if inventory_response.status_code != 200:
            # COMPENSATION: inventory not available - cancel the order
            print(f"[SAGA] Step 2 FAILED: {inventory_response.text}")
            await _cancel_order(order, "Ingredients not available", db)
            return {"success": False, "error": "Ingredients not available"}

    except httpx.RequestError as e:
        # inventory-service is unreachable
        print(f"[SAGA] Step 2 ERROR: inventory-service unreachable - {e}")
        await _cancel_order(order, "Inventory service unavailable", db)
        return {"success": False, "error": "Inventory service unavailable"}

    print(f"[SAGA] Step 2 OK: Inventory reserved")

    # ── Step 3: Create bill in billing-service ─────────────────────────────────
    print(f"[SAGA] Step 3: Creating bill for order {order.id}")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            billing_response = await client.post(
                f"{BILLING_SERVICE_URL}/bills",
                json={
                    "order_id": order.id,
                    "table_id": order.table_id,
                    "total_amount": float(order.total_amount)
                }
            )

        if billing_response.status_code != 200:
            # COMPENSATION: billing failed - release inventory and cancel order
            print(f"[SAGA] Step 3 FAILED: {billing_response.text}")
            await _release_inventory(order.id)
            await _cancel_order(order, "Billing failed", db)
            return {"success": False, "error": "Billing failed"}

    except httpx.RequestError as e:
        print(f"[SAGA] Step 3 ERROR: billing-service unreachable - {e}")
        await _release_inventory(order.id)
        await _cancel_order(order, "Billing service unavailable", db)
        return {"success": False, "error": "Billing service unavailable"}

    print(f"[SAGA] Step 3 OK: Bill created")

    # ── Step 4: Confirm order ──────────────────────────────────────────────────
    print(f"[SAGA] Step 4: Confirming order {order.id}")

    order.status = "CONFIRMED"
    order.updated_at = datetime.utcnow()

    # Write outbox event in the same transaction as status update
    outbox_event = OutboxEvent(
        event_type="ORDER_CONFIRMED",
        payload={
            "order_id": order.id,
            "table_id": order.table_id,
            "customer_name": order.customer_name,
            "status": "CONFIRMED",
            "items": order.items,
            "total_amount": float(order.total_amount)
        }
    )
    db.add(outbox_event)
    await db.commit()

    print(f"[SAGA] COMPLETED: Order {order.id} confirmed")
    return {"success": True, "order": order}


async def _cancel_order(order: Order, reason: str, db: AsyncSession):
    """Compensating action: marks the order as CANCELLED."""
    order.status = "CANCELLED"
    order.updated_at = datetime.utcnow()

    outbox_event = OutboxEvent(
        event_type="ORDER_CANCELLED",
        payload={
            "order_id": order.id,
            "table_id": order.table_id,
            "reason": reason
        }
    )
    db.add(outbox_event)
    await db.commit()
    print(f"[SAGA] COMPENSATED: Order {order.id} cancelled - {reason}")


async def _release_inventory(order_id: str):
    """Compensating action: tells inventory-service to release reserved ingredients."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{INVENTORY_SERVICE_URL}/inventory/release",
                json={"order_id": order_id}
            )
        print(f"[SAGA] COMPENSATED: Inventory released for order {order_id}")
    except httpx.RequestError as e:
        # Log but don't crash - this would need retry logic in production
        print(f"[SAGA] WARNING: Could not release inventory for {order_id}: {e}")
