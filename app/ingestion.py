import logging
import json
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.models import DetectionEvent

logger = logging.getLogger(__name__)


async def ingest_events(events: List[DetectionEvent], db: AsyncSession) -> dict:
    """Idempotent batch insert using ON CONFLICT DO NOTHING."""
    if not events:
        return {"inserted": 0, "duplicates": 0}

    rows = []
    for e in events:
        rows.append({
            "event_id": e.event_id,
            "store_id": e.store_id,
            "camera_id": e.camera_id,
            "visitor_id": e.visitor_id,
            "event_type": e.event_type,
            "timestamp": e.timestamp,
            "zone_id": e.zone_id,
            "dwell_ms": e.dwell_ms,
            "is_staff": e.is_staff,
            "confidence": e.confidence,
            "metadata": json.dumps(e.metadata.model_dump()) if e.metadata else None,
        })

    # Bulk upsert — idempotent via event_id primary key
    insert_sql = text("""
        INSERT INTO events
            (event_id, store_id, camera_id, visitor_id, event_type,
             timestamp, zone_id, dwell_ms, is_staff, confidence, metadata)
        VALUES
            (:event_id, :store_id, :camera_id, :visitor_id, :event_type,
             :timestamp, :zone_id, :dwell_ms, :is_staff, :confidence, CAST(:metadata AS JSONB))
        ON CONFLICT (event_id) DO NOTHING
    """)

    result = await db.execute(insert_sql, rows)
    await db.commit()

    inserted = result.rowcount
    duplicates = len(events) - inserted

    # Update camera heartbeats
    heartbeat_sql = text("""
        INSERT INTO camera_heartbeats (store_id, camera_id, last_seen)
        SELECT DISTINCT store_id, camera_id, NOW()
        FROM events
        WHERE event_id = ANY(:ids)
        ON CONFLICT (store_id, camera_id) DO UPDATE SET last_seen = NOW()
    """)
    await db.execute(heartbeat_sql, {"ids": [e.event_id for e in events]})
    await db.commit()

    logger.info(
        "ingest_complete",
        extra={"inserted": inserted, "duplicates": duplicates, "batch_size": len(events)}
    )
    return {"inserted": inserted, "duplicates": duplicates}
