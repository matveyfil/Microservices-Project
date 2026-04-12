import asyncio
from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.database import engine, Base
from app.routes import router
from app.outbox_worker import run_outbox_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[BILLING SERVICE] Database tables created")

    outbox_task = asyncio.create_task(run_outbox_worker())

    yield

    outbox_task.cancel()


app = FastAPI(
    title="Billing Service",
    description="Manages bills and payments. Participates in the Order Placement Saga.",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"service": "billing-service", "status": "ok"}
