from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

QUEUE_SPIKE_THRESHOLD = 5          # queue depth above this = spike
DEAD_ZONE_MINUTES = 30             # no visitors in zone for X mins = dead zone
CONVERSION_DROP_THRESHOLD = 0.20   # 20% drop vs 7-day avg = anomaly


async def get_anomalies(store_id: str, db: AsyncSession) -> dict:
    anomalies = []

    # --- 1. BILLING_QUEUE_SPIKE ---
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
    queue_depth = max(queue_result.scalar() or 0, 0)

    if queue_depth >= QUEUE_SPIKE_THRESHOLD:
        anomalies.append({
            "type": "BILLING_QUEUE_SPIKE",
            "severity": "HIGH" if queue_depth >= QUEUE_SPIKE_THRESHOLD * 2 else "MEDIUM",
            "message": f"Queue depth is {queue_depth} (threshold: {QUEUE_SPIKE_THRESHOLD})",
            "value": queue_depth,
            "detected_at": datetime.utcnow().isoformat() + "Z",
        })

    # --- 2. DEAD_ZONE ---
    dead_zone_result = await db.execute(text("""
        SELECT DISTINCT zone_id
        FROM events
        WHERE store_id = :store_id
          AND is_staff = FALSE
          AND zone_id IS NOT NULL
          AND timestamp < NOW() - INTERVAL '30 minutes'
          AND timestamp >= CURRENT_DATE
        EXCEPT
        SELECT DISTINCT zone_id
        FROM events
        WHERE store_id = :store_id
          AND is_staff = FALSE
          AND zone_id IS NOT NULL
          AND timestamp >= NOW() - INTERVAL '30 minutes'
    """), {"store_id": store_id})
    dead_zones = [row.zone_id for row in dead_zone_result]

    for zone_id in dead_zones:
        anomalies.append({
            "type": "DEAD_ZONE",
            "severity": "LOW",
            "message": f"Zone '{zone_id}' has had no visitors in the last {DEAD_ZONE_MINUTES} minutes",
            "zone_id": zone_id,
            "detected_at": datetime.utcnow().isoformat() + "Z",
        })

    # --- 3. CONVERSION_DROP ---
    # Today's conversion rate vs 7-day rolling average
    today_result = await db.execute(text("""
        SELECT
            COUNT(DISTINCT CASE WHEN event_type = 'ENTRY' THEN visitor_id END) AS total,
            COUNT(DISTINCT CASE WHEN event_type = 'BILLING_QUEUE_JOIN' THEN visitor_id END) AS billing
        FROM events
        WHERE store_id = :store_id
          AND is_staff = FALSE
          AND timestamp >= CURRENT_DATE
    """), {"store_id": store_id})
    today = today_result.fetchone()
    today_rate = (today.billing / today.total) if today.total and today.total > 0 else None

    avg_result = await db.execute(text("""
        SELECT
            COUNT(DISTINCT CASE WHEN event_type = 'ENTRY' THEN visitor_id END) AS total,
            COUNT(DISTINCT CASE WHEN event_type = 'BILLING_QUEUE_JOIN' THEN visitor_id END) AS billing
        FROM events
        WHERE store_id = :store_id
          AND is_staff = FALSE
          AND timestamp >= CURRENT_DATE - INTERVAL '7 days'
          AND timestamp < CURRENT_DATE
    """), {"store_id": store_id})
    avg_row = avg_result.fetchone()
    avg_rate = (avg_row.billing / avg_row.total) if avg_row.total and avg_row.total > 0 else None

    if today_rate is not None and avg_rate is not None and avg_rate > 0:
        drop = (avg_rate - today_rate) / avg_rate
        if drop >= CONVERSION_DROP_THRESHOLD:
            anomalies.append({
                "type": "CONVERSION_DROP",
                "severity": "HIGH",
                "message": f"Conversion rate dropped {round(drop * 100, 1)}% vs 7-day avg ({round(today_rate * 100, 1)}% vs {round(avg_rate * 100, 1)}%)",
                "today_rate": round(today_rate, 4),
                "avg_7d_rate": round(avg_rate, 4),
                "drop_pct": round(drop * 100, 1),
                "detected_at": datetime.utcnow().isoformat() + "Z",
            })

    return {
        "store_id": store_id,
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
    }
