import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, JSON, Boolean, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class Ingredient(Base):
    """
    Tracks stock levels for each ingredient.
    This is the source of truth for inventory.
    """
    __tablename__ = "ingredients"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)  # current stock
    unit: Mapped[str] = mapped_column(String, nullable=False)       # kg, litres, pieces
    threshold: Mapped[int] = mapped_column(Integer, nullable=False) # low stock threshold
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InventoryReservation(Base):
    """
    Tracks ingredient reservations per order.
    When an order is placed, ingredients are reserved here.
    If the order is cancelled, reservation is released.
    """
    __tablename__ = "inventory_reservations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    order_id: Mapped[str] = mapped_column(String, nullable=False)
    # items stored as JSON: [{"name": "pasta", "quantity": 2}]
    reserved_items: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, default="RESERVED")
    # RESERVED → CONSUMED (order completed) or RELEASED (order cancelled)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OutboxEvent(Base):
    """Outbox table for inventory events."""
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
