import logging
import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, HTTPException, Request, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DetectionEvent
from app.database import init_db, get_db
import app.ingestion as ingestion_svc
import app.metrics as metrics_svc
import app.funnel as funnel_svc
import app.anomalies as anomalies_svc
import app.health as health_svc

# --- Structured JSON Logger ---
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        if hasattr(record, "trace_id"):
            log["trace_id"] = record.trace_id
        if hasattr(record, "latency_ms"):
            log["latency_ms"] = record.latency_ms
        if hasattr(record, "status_code"):
            log["status_code"] = record.status_code
        log.update({k: v for k, v in record.__dict__.items()
                    if k not in ("msg", "args", "levelname", "levelno", "pathname",
                                 "filename", "module", "exc_info", "exc_text",
                                 "stack_info", "lineno", "funcName", "created",
                                 "msecs", "relativeCreated", "thread", "threadName",
                                 "processName", "process", "message", "name",
                                 "taskName")})
        return json.dumps(log)

handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", extra={"detail": "Initialising database schema"})
    await init_db()
    logger.info("startup", extra={"detail": "Database ready"})
    yield
    logger.info("shutdown", extra={"detail": "Shutting down"})


app = FastAPI(
    title="Apex Retail Store Intelligence API",
    description="Real-time store analytics: visitors, conversion, funnel, anomalies.",
    version="1.0.0",
    lifespan=lifespan,
)


# --- Request logging middleware ---
@app.middleware("http")
async def log_requests(request: Request, call_next):
    trace_id = str(uuid.uuid4())[:8]
    start = time.time()
    response = await call_next(request)
    latency_ms = round((time.time() - start) * 1000, 1)
    logger.info(
        f"{request.method} {request.url.path}",
        extra={"trace_id": trace_id, "latency_ms": latency_ms, "status_code": response.status_code}
    )
    response.headers["X-Trace-Id"] = trace_id
    return response


# ---------- Endpoints ----------

@app.get("/health", tags=["System"])
async def health_check(db: AsyncSession = Depends(get_db)):
    return await health_svc.get_health(db)


@app.post("/events/ingest", status_code=status.HTTP_202_ACCEPTED, tags=["Ingestion"])
async def ingest_events(events: List[DetectionEvent], db: AsyncSession = Depends(get_db)):
    if len(events) > 500:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Batch size exceeds limit of 500 events."
        )
    if not events:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty batch."
        )
    result = await ingestion_svc.ingest_events(events, db)
    return {
        "message": f"Successfully ingested {len(events)} events",
        "inserted": result["inserted"],
        "duplicates": result["duplicates"],
    }


@app.get("/stores/{store_id}/metrics", tags=["Analytics"])
async def get_metrics(store_id: str, db: AsyncSession = Depends(get_db)):
    return await metrics_svc.get_store_metrics(store_id, db)


@app.get("/stores/{store_id}/funnel", tags=["Analytics"])
async def get_funnel(store_id: str, db: AsyncSession = Depends(get_db)):
    return await funnel_svc.get_funnel(store_id, db)


@app.get("/stores/{store_id}/heatmap", tags=["Analytics"])
async def get_heatmap(store_id: str, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import text
    result = await db.execute(text("""
        SELECT
            zone_id,
            COUNT(DISTINCT visitor_id) AS visit_count,
            ROUND(AVG(dwell_ms)::numeric, 0)::int AS avg_dwell_ms
        FROM events
        WHERE store_id = :store_id
          AND is_staff = FALSE
          AND zone_id IS NOT NULL
          AND event_type IN ('ZONE_ENTER', 'ZONE_DWELL')
          AND timestamp >= CURRENT_DATE
        GROUP BY zone_id
        ORDER BY visit_count DESC
    """), {"store_id": store_id})
    rows = result.fetchall()

    max_visits = max((r.visit_count for r in rows), default=1)
    heatmap = [
        {
            "zone_id": r.zone_id,
            "visit_count": r.visit_count,
            "avg_dwell_ms": r.avg_dwell_ms,
            "heat_score": round(r.visit_count / max_visits * 100, 1),
        }
        for r in rows
    ]
    return {"store_id": store_id, "heatmap": heatmap}


@app.get("/stores/{store_id}/anomalies", tags=["Analytics"])
async def get_anomalies(store_id: str, db: AsyncSession = Depends(get_db)):
    return await anomalies_svc.get_anomalies(store_id, db)
