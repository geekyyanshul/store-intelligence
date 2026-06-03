from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

STALE_FEED_MINUTES = 5


async def get_health(db: AsyncSession) -> dict:
    """Service health check with stale feed warnings."""
    warnings = []
    db_status = "ok"

    # Check DB connectivity
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = "error"
        logger.error("db_health_check_failed", extra={"error": str(e)})

    # Check for stale feeds (cameras with no events in last 5 min)
    try:
        stale_result = await db.execute(text("""
            SELECT store_id, camera_id, last_seen,
                   EXTRACT(EPOCH FROM (NOW() - last_seen)) / 60 AS stale_minutes
            FROM camera_heartbeats
            WHERE last_seen < NOW() - INTERVAL '5 minutes'
            ORDER BY stale_minutes DESC
        """))
        stale_feeds = stale_result.fetchall()
        for feed in stale_feeds:
            warnings.append({
                "type": "STALE_FEED",
                "store_id": feed.store_id,
                "camera_id": feed.camera_id,
                "last_seen": feed.last_seen.isoformat() if feed.last_seen else None,
                "stale_minutes": round(feed.stale_minutes, 1),
            })
    except Exception:
        pass  # Table might not exist yet

    status = "degraded" if (warnings or db_status == "error") else "ok"

    return {
        "status": status,
        "db": db_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "warnings": warnings,
    }
