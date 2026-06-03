from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


async def get_store_metrics(store_id: str, db: AsyncSession) -> dict:
    """
    Compute today's store metrics from stored events:
    - unique_visitors
    - conversion_rate
    - avg_dwell_per_zone
    - current_queue_depth
    - abandonment_rate
    """

    # Unique non-staff visitors today
    visitors_result = await db.execute(text("""
        SELECT COUNT(DISTINCT visitor_id) as unique_visitors
        FROM events
        WHERE store_id = :store_id
          AND is_staff = FALSE
          AND event_type = 'ENTRY'
          AND timestamp >= CURRENT_DATE
    """), {"store_id": store_id})
    unique_visitors = visitors_result.scalar() or 0

    # Visitors who joined billing queue (proxy for purchase intent)
    billing_result = await db.execute(text("""
        SELECT COUNT(DISTINCT visitor_id) as billing_visitors
        FROM events
        WHERE store_id = :store_id
          AND is_staff = FALSE
          AND event_type = 'BILLING_QUEUE_JOIN'
          AND timestamp >= CURRENT_DATE
    """), {"store_id": store_id})
    billing_visitors = billing_result.scalar() or 0

    conversion_rate = round(billing_visitors / unique_visitors, 4) if unique_visitors > 0 else 0.0

    # Average dwell per zone
    dwell_result = await db.execute(text("""
        SELECT zone_id, ROUND(AVG(dwell_ms)::numeric, 0)::int AS avg_dwell_ms
        FROM events
        WHERE store_id = :store_id
          AND is_staff = FALSE
          AND event_type = 'ZONE_DWELL'
          AND zone_id IS NOT NULL
          AND timestamp >= CURRENT_DATE
        GROUP BY zone_id
        ORDER BY avg_dwell_ms DESC
    """), {"store_id": store_id})
    avg_dwell_per_zone = {row.zone_id: row.avg_dwell_ms for row in dwell_result}

    # Current queue depth (joins minus exits/abandons in last 30 min)
    queue_result = await db.execute(text("""
        SELECT
            SUM(CASE WHEN event_type = 'BILLING_QUEUE_JOIN' THEN 1 ELSE 0 END) -
            SUM(CASE WHEN event_type IN ('BILLING_QUEUE_ABANDON', 'EXIT') THEN 1 ELSE 0 END) AS depth
        FROM events
        WHERE store_id = :store_id
          AND is_staff = FALSE
          AND event_type IN ('BILLING_QUEUE_JOIN', 'BILLING_QUEUE_ABANDON', 'EXIT')
          AND timestamp >= NOW() - INTERVAL '30 minutes'
    """), {"store_id": store_id})
    current_queue_depth = max(queue_result.scalar() or 0, 0)

    # Abandonment rate
    abandon_result = await db.execute(text("""
        SELECT COUNT(DISTINCT visitor_id) as abandoned
        FROM events
        WHERE store_id = :store_id
          AND is_staff = FALSE
          AND event_type = 'BILLING_QUEUE_ABANDON'
          AND timestamp >= CURRENT_DATE
    """), {"store_id": store_id})
    abandoned = abandon_result.scalar() or 0
    abandonment_rate = round(abandoned / billing_visitors, 4) if billing_visitors > 0 else 0.0

    return {
        "store_id": store_id,
        "date": "today",
        "metrics": {
            "unique_visitors": unique_visitors,
            "conversion_rate": conversion_rate,
            "billing_queue_visitors": billing_visitors,
            "current_queue_depth": current_queue_depth,
            "abandonment_rate": abandonment_rate,
            "avg_dwell_ms_per_zone": avg_dwell_per_zone,
        }
    }
