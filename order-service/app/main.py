import asyncio
from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.database import engine, Base
from app.routes import commands, queries
from app.outbox_worker import run_outbox_worker
from app.event_consumer import run_event_consumer


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    # Create all DB tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[ORDER SERVICE] Database tables created")

    # Start background workers as async tasks
    outbox_task = asyncio.create_task(run_outbox_worker())
    consumer_task = asyncio.create_task(run_event_consumer())
    print("[ORDER SERVICE] Background workers started")

    yield  # app is running

    # ── Shutdown ─────────────────────────────────────────────────────────────
    outbox_task.cancel()
    consumer_task.cancel()
    print("[ORDER SERVICE] Shutting down")


app = FastAPI(
    title="Order Service",
    description="Manages order lifecycle. Implements Saga (orchestrator), CQRS, and Transactional Outbox.",
    version="1.0.0",
    lifespan=lifespan
)

# Register routes
app.include_router(commands.router, tags=["Commands (Write)"])
app.include_router(queries.router, tags=["Queries (Read)"])


@app.get("/health")
async def health():
    return {"service": "order-service", "status": "ok"}
