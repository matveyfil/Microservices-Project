"""
Event Consumer - CQRS Read Model Updater

This background worker listens to Redis Streams for events from other services.
When it receives an event, it updates the order_projections table (read model).

This is the event-driven synchronisation part of CQRS:
  Write model (orders table) ← updated by commands
  Read model (order_projections) ← updated by this consumer via events

For example, when billing-service publishes ORDER_PAID event,
this consumer updates the projection so kitchen dashboard shows correct status.
"""

import asyncio
import json
import os
import redis.asyncio as redis
from datetime import datetime
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import OrderProjection

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

ORDERS_STREAM = "orders.events"
CONSUMER_GROUP = "order-service-projections"
CONSUMER_NAME = "order-service-consumer-1"


async def run_event_consumer():
    """
    Listens to Redis Streams and updates read projections.
    Uses consumer groups so events are not missed if service restarts.
    """
    redis_client = redis.from_url(REDIS_URL)

    # Create consumer group if it doesn't exist
    try:
        await redis_client.xgroup_create(ORDERS_STREAM, CONSUMER_GROUP, id="0", mkstream=True)
        print(f"[CONSUMER] Created consumer group: {CONSUMER_GROUP}")
    except Exception:
        pass  # group already exists

    print("[CONSUMER] Event consumer started")

    while True:
        try:
            # Read new messages from the stream
            messages = await redis_client.xreadgroup(
                CONSUMER_GROUP,
                CONSUMER_NAME,
                {ORDERS_STREAM: ">"},  # ">" means only new, undelivered messages
                count=10,
                block=2000  # wait up to 2 seconds for new messages
            )

            if messages:
                for stream_name, events in messages:
                    for event_id, event_data in events:
                        await _handle_event(event_data, redis_client, event_id)

        except Exception as e:
            print(f"[CONSUMER] Error: {e}")
            await asyncio.sleep(2)


async def _handle_event(event_data: dict, redis_client, event_id: str):
    """Handles a single event and updates the read projection."""
    event_type = event_data.get(b"event_type", b"").decode()
    payload = json.loads(event_data.get(b"payload", b"{}").decode())

    print(f"[CONSUMER] Received event: {event_type}")

    async with AsyncSessionLocal() as db:
        if event_type == "ORDER_CONFIRMED":
            # Upsert the projection (create or update)
            result = await db.execute(
                select(OrderProjection).where(OrderProjection.id == payload["order_id"])
            )
            projection = result.scalar_one_or_none()

            if not projection:
                projection = OrderProjection(
                    id=payload["order_id"],
                    table_id=payload["table_id"],
                    customer_name=payload.get("customer_name", ""),
                    items=payload["items"],
                    total_amount=payload["total_amount"],
                    status="CONFIRMED",
                    created_at=datetime.utcnow()
                )
                db.add(projection)
            else:
                projection.status = "CONFIRMED"
                projection.updated_at = datetime.utcnow()

            await db.commit()

        elif event_type in ("ORDER_CANCELLED", "ORDER_STATUS_UPDATED"):
            result = await db.execute(
                select(OrderProjection).where(OrderProjection.id == payload["order_id"])
            )
            projection = result.scalar_one_or_none()
            if projection:
                projection.status = payload.get("status", "CANCELLED")
                projection.updated_at = datetime.utcnow()
                await db.commit()

    # Acknowledge the message so Redis knows it was processed
    await redis_client.xack(ORDERS_STREAM, CONSUMER_GROUP, event_id)
