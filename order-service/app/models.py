import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, JSON, Boolean, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


def generate_uuid():
    return str(uuid.uuid4())


# ─── Write Model (Command side of CQRS) ────────────────────────────────────────

class Order(Base):
    """
    Main orders table - this is the WRITE model (command side of CQRS).
    All state changes go here first.
    """
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    table_id: Mapped[str] = mapped_column(String, nullable=False)
    customer_name: Mapped[str] = mapped_column(String, nullable=False)
    # items stored as JSON: [{"name": "pasta", "quantity": 2, "price": 12.50}]
    items: Mapped[dict] = mapped_column(JSON, nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    # Possible statuses:
    # PENDING → CONFIRMED → IN_PREPARATION → READY → SERVED → PAID → CLOSED
    # PENDING → CANCELLED (if saga fails)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ─── Read Model (Query side of CQRS) ───────────────────────────────────────────

class OrderProjection(Base):
    """
    Read-optimised projection of orders - this is the READ model (query side of CQRS).
    This table is updated asynchronously via Redis events.
    Kitchen staff and dashboards query this table, not the main orders table.

    Why separate? Read queries can be optimised differently from write operations.
    For example, kitchen staff only need: id, table_id, items, status.
    """
    __tablename__ = "order_projections"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    table_id: Mapped[str] = mapped_column(String, nullable=False)
    customer_name: Mapped[str] = mapped_column(String, nullable=False)
    items: Mapped[dict] = mapped_column(JSON, nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ─── Transactional Outbox ───────────────────────────────────────────────────────

class OutboxEvent(Base):
    """
    Outbox table - core of the Transactional Outbox pattern.

    When we update an order, we also INSERT a row here IN THE SAME TRANSACTION.
    This guarantees that if the DB write succeeds, the event will eventually
    be published to Redis. No dual-write inconsistency possible.

    A background worker reads unpublished events and sends them to Redis Streams.
    """
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    # event_type examples: "ORDER_CREATED", "ORDER_CONFIRMED", "ORDER_CANCELLED"
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
