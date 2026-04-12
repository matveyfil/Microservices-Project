import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, JSON, Boolean, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class Bill(Base):
    """
    A bill is created when an order is confirmed.
    It tracks payment status for that order.
    """
    __tablename__ = "bills"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    order_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    table_id: Mapped[str] = mapped_column(String, nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    # PENDING → PAID or PENDING → FAILED → PAID (retry) or CANCELLED
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OutboxEvent(Base):
    """Outbox table for billing events."""
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
