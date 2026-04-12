"""
Outbox Worker - Transactional Outbox Pattern

This background worker runs every 3 seconds.
It reads unpublished events from the outbox table and publishes them to Redis Streams.

Why do we need this?
Without the outbox pattern, we might:
  1. Update the DB → success
  2. Publish to Redis → FAIL (network issue, Redis down)
  Result: DB updated but event never sent → inconsistency

With outbox:
  1. Update DB + write to outbox → single transaction (atomic)
  2. Worker reads outbox → publishes to Redis → marks as published
  Result: Even if step 2 fails, we retry. The DB state and events are always consistent.
"""

import asyncio
import json
import os
import redis.asyncio as redis
from sqlalchemy import select, update
from app.database import AsyncSessionLocal
from app.models import OutboxEvent

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Redis Stream name - all order events go here
ORDERS_STREAM = "orders.events"


async def run_outbox_worker():
    """
    Polls the outbox table every 3 seconds.
    Publishes unpublished events to Redis Streams.
    """
    redis_client = redis.from_url(REDIS_URL)
    print("[OUTBOX] Worker started")

    while True:
        try:
            await _process_pending_events(redis_client)
        except Exception as e:
            print(f"[OUTBOX] Error: {e}")

        await asyncio.sleep(3)  # poll every 3 seconds


async def _process_pending_events(redis_client):
    """Reads all unpublished outbox events and publishes them to Redis."""
    async with AsyncSessionLocal() as db:
        # Get all unpublished events, oldest first
        result = await db.execute(
            select(OutboxEvent)
            .where(OutboxEvent.published == False)
            .order_by(OutboxEvent.created_at)
            .limit(10)  # process max 10 at a time
        )
        events = result.scalars().all()

        if not events:
            return  # nothing to publish

        for event in events:
            # Publish event to Redis Stream
            await redis_client.xadd(
                ORDERS_STREAM,
                {
                    "event_type": event.event_type,
                    "payload": json.dumps(event.payload)
                }
            )
            print(f"[OUTBOX] Published event: {event.event_type} (id={event.id})")

            # Mark as published
            event.published = True

        await db.commit()
