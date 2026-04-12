import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

# Read database URL from environment variable (set in docker-compose.yml)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:password@localhost:5432/order_db")

# Create async engine - this is the connection to PostgreSQL
engine = create_async_engine(DATABASE_URL, echo=True)

# Session factory - we use this to create DB sessions in route handlers
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# Base class for all SQLAlchemy models
class Base(DeclarativeBase):
    pass

# Dependency - used in FastAPI routes to get a DB session
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
