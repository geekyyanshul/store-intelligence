import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy import Column, Text, Integer, Boolean, Float, DateTime, JSON, text

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://admin:password@localhost:5432/store_intelligence"
)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    """Create tables on startup."""
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS events (
                event_id    TEXT PRIMARY KEY,
                store_id    TEXT NOT NULL,
                camera_id   TEXT NOT NULL,
                visitor_id  TEXT NOT NULL,
                event_type  TEXT NOT NULL,
                timestamp   TIMESTAMPTZ NOT NULL,
                zone_id     TEXT,
                dwell_ms    INTEGER NOT NULL DEFAULT 0,
                is_staff    BOOLEAN NOT NULL DEFAULT FALSE,
                confidence  FLOAT NOT NULL,
                metadata    JSONB,
                ingested_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_events_store_time
            ON events (store_id, timestamp DESC)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_events_visitor
            ON events (visitor_id, timestamp)
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS camera_heartbeats (
                store_id    TEXT NOT NULL,
                camera_id   TEXT NOT NULL,
                last_seen   TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (store_id, camera_id)
            )
        """))


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
