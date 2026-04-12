import asyncio
import json
import os
import redis.asyncio as redis
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import OutboxEvent

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
RESERVATION_STREAM = "reservation.events"


async def run_outbox_worker():
    redis_client = redis.from_url(REDIS_URL)
    print("[OUTBOX] Reservation outbox worker started")

    while True:
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(OutboxEvent)
                    .where(OutboxEvent.published == False)
                    .order_by(OutboxEvent.created_at)
                    .limit(10)
                )
                events = result.scalars().all()

                for event in events:
                    await redis_client.xadd(
                        RESERVATION_STREAM,
                        {
                            "event_type": event.event_type,
                            "payload": json.dumps(event.payload)
                        }
                    )
                    print(f"[OUTBOX] Published: {event.event_type}")
                    event.published = True

                if events:
                    await db.commit()

        except Exception as e:
            print(f"[OUTBOX] Error: {e}")

        await asyncio.sleep(3)
