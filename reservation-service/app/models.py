import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, JSON, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class Table(Base):
    """Restaurant tables."""
    __tablename__ = "tables"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    number: Mapped[str] = mapped_column(String, unique=True, nullable=False)  # e.g. "T1", "T2"
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, default="AVAILABLE")
    # AVAILABLE, OCCUPIED, RESERVED


class Reservation(Base):
    """
    A table reservation. Protects against double-booking
    by checking capacity before confirming.
    """
    __tablename__ = "reservations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    table_id: Mapped[str] = mapped_column(String, nullable=False)
    customer_name: Mapped[str] = mapped_column(String, nullable=False)
    party_size: Mapped[int] = mapped_column(Integer, nullable=False)
    time_slot: Mapped[str] = mapped_column(String, nullable=False)  # "2024-01-15 19:00"
    status: Mapped[str] = mapped_column(String, default="REQUESTED")
    # REQUESTED → CONFIRMED → ACTIVE → COMPLETED
    # REQUESTED → CANCELLED
    # CONFIRMED → NO_SHOW (if customer doesn't arrive)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OutboxEvent(Base):
    """Outbox table for reservation events."""
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
