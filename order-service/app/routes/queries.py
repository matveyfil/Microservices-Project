"""
Query Routes - Read side of CQRS

These routes handle read-only operations.
They query the order_projections table (read model), NOT the orders table.

Why read from projections?
- Projections are optimised for specific views (kitchen, dashboard)
- Read queries don't block write operations
- We can add indexes on projections without affecting write performance
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.database import get_db
from app.models import Order, OrderProjection
from app.schemas import OrderResponse, KitchenOrderView

router = APIRouter()


@router.get("/orders", response_model=List[OrderResponse])
async def get_all_orders(db: AsyncSession = Depends(get_db)):
    """Get all orders (admin view). Reads from write model."""
    result = await db.execute(select(Order).order_by(Order.created_at.desc()))
    return result.scalars().all()


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(order_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single order by ID."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.get("/orders/kitchen/active", response_model=List[KitchenOrderView])
async def get_kitchen_orders(db: AsyncSession = Depends(get_db)):
    """
    Kitchen dashboard - shows active orders that need attention.
    Reads from READ MODEL (order_projections), not the orders table.
    This is the CQRS read path.
    """
    result = await db.execute(
        select(OrderProjection)
        .where(OrderProjection.status.in_(["CONFIRMED", "IN_PREPARATION", "ON_HOLD"]))
        .order_by(OrderProjection.created_at)
    )
    return result.scalars().all()


@router.get("/orders/dashboard/summary")
async def get_dashboard_summary(db: AsyncSession = Depends(get_db)):
    """
    Operations manager dashboard.
    Returns count of orders per status.
    Reads from READ MODEL.
    """
    result = await db.execute(select(OrderProjection))
    all_orders = result.scalars().all()

    summary = {}
    for order in all_orders:
        summary[order.status] = summary.get(order.status, 0) + 1

    return {
        "total_orders": len(all_orders),
        "by_status": summary
    }
