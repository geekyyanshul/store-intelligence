from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)


async def get_funnel(store_id: str, db: AsyncSession) -> dict:
    """
    Session-based conversion funnel:
    Entry → Zone Visit → Billing Queue → Purchase (inferred)

    A session is all events per visitor within a 2-hour window.
    """

    result = await db.execute(text("""
        WITH visitor_stages AS (
            SELECT
                visitor_id,
                MAX(CASE WHEN event_type = 'ENTRY' THEN 1 ELSE 0 END) AS entered,
                MAX(CASE WHEN event_type IN ('ZONE_ENTER', 'ZONE_DWELL') THEN 1 ELSE 0 END) AS explored_zone,
                MAX(CASE WHEN event_type = 'BILLING_QUEUE_JOIN' THEN 1 ELSE 0 END) AS joined_billing,
                MAX(CASE WHEN event_type = 'BILLING_QUEUE_ABANDON' THEN 1 ELSE 0 END) AS abandoned_billing
            FROM events
            WHERE store_id = :store_id
              AND is_staff = FALSE
              AND timestamp >= CURRENT_DATE
            GROUP BY visitor_id
        )
        SELECT
            SUM(entered)         AS stage_entry,
            SUM(explored_zone)   AS stage_zone_explored,
            SUM(joined_billing)  AS stage_billing_queue,
            SUM(CASE WHEN joined_billing = 1 AND abandoned_billing = 0 THEN 1 ELSE 0 END) AS stage_purchase
        FROM visitor_stages
    """), {"store_id": store_id})

    row = result.fetchone()
    stage_entry = row.stage_entry or 0
    stage_zone = row.stage_zone_explored or 0
    stage_billing = row.stage_billing_queue or 0
    stage_purchase = row.stage_purchase or 0

    def drop_pct(from_val, to_val):
        if from_val == 0:
            return 0.0
        return round((from_val - to_val) / from_val * 100, 1)

    return {
        "store_id": store_id,
        "funnel": {
            "stages": [
                {"name": "Entry",         "visitors": stage_entry,    "drop_off_pct": 0.0},
                {"name": "Zone Explored", "visitors": stage_zone,     "drop_off_pct": drop_pct(stage_entry, stage_zone)},
                {"name": "Billing Queue", "visitors": stage_billing,  "drop_off_pct": drop_pct(stage_zone, stage_billing)},
                {"name": "Purchase",      "visitors": stage_purchase, "drop_off_pct": drop_pct(stage_billing, stage_purchase)},
            ],
            "overall_conversion_rate": round(stage_purchase / stage_entry, 4) if stage_entry > 0 else 0.0,
        }
    }
