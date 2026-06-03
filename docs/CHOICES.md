# CHOICES.md — Design Decisions

This document covers three major technical decisions made during the build of the Store Intelligence system, including the reasoning, alternatives considered, and where I disagreed with AI suggestions.

---

## Decision 1: Detection Model — YOLOv8 (nano) over alternatives

### Context
The challenge requires detecting persons in CCTV footage. The detection model is the foundation of the entire pipeline — its accuracy directly determines the accuracy of the North Star metric (conversion rate).

### Options Considered

| Model | Pros | Cons |
|-------|------|------|
| **YOLOv8n** (chosen) | Fast CPU inference (~40ms/frame), pre-trained on COCO persons, Python SDK, easy integration with Ultralytics tracker | Lower accuracy than larger models on small/occluded persons |
| YOLOv8m | Better accuracy | ~3x slower, not suitable for real-time on CPU |
| Detectron2 (Faster R-CNN) | High accuracy | Complex setup, slow inference, poor real-time characteristics |
| GPT-4V / Gemini Vision | Can handle complex scene understanding | ~500ms latency per frame, cost-prohibitive at scale, no bounding box output |
| OpenPose | Pose estimation | Not suitable for person counting, no bounding box |

### Decision
YOLOv8n with confidence threshold 0.5. The nano model is fast enough for real-time processing while delivering sufficient accuracy for person detection in well-lit retail environments.

### Where I Disagreed with AI
The AI (Gemini) initially recommended using YOLOv8m for better accuracy. I pushed back: the challenge evaluates edge case handling, not raw accuracy. A faster model that processes more frames and handles re-entry/occlusion better via tracking is more valuable than a slower but more accurate detector. I chose YOLOv8n and invested the saved compute budget into the tracking layer.

### Trade-off Acknowledged
YOLOv8n struggles with highly occluded scenes and small persons in wide-angle shots. For production at 40 stores, I would A/B test YOLOv8n vs YOLOv8s on the specific camera setups and select per-camera.

---

## Decision 2: Database — PostgreSQL over SQLite

### Context
Events need to be stored and queried for real-time metrics, funnel computation, and anomaly detection. The storage choice affects query flexibility, concurrency, and production readiness.

### Options Considered

| Database | Pros | Cons |
|----------|------|------|
| **PostgreSQL** (chosen) | ACID, concurrent writes from multiple pipeline instances, rich SQL (window functions for funnel), JSONB for metadata, docker-native | Heavier setup, requires separate container |
| SQLite | Zero setup, single file, simple | No concurrent writes, no JSONB, not production-suitable |
| Redis | Fast time-series aggregations | Not durable without AOF, no complex SQL, harder to query historical data |
| TimescaleDB | Purpose-built for time-series | Adds complexity, overkill for this scale |

### Decision
PostgreSQL. The funnel query requires window functions (`LAG`, `LEAD`, `PARTITION BY visitor_id ORDER BY timestamp`) that are natural in PostgreSQL and painful in SQLite. Multi-instance pipeline scenarios also require concurrent writes which SQLite cannot handle.

### Where I Disagreed with AI
The AI suggested SQLite as "simpler for a take-home project." I disagreed because the challenge explicitly asks about production scalability in the follow-up questions (e.g., "at 40 live stores, what breaks first?"). Using PostgreSQL from the start allows me to answer those questions honestly.

### Trade-off Acknowledged
PostgreSQL adds Docker complexity. If the acceptance gate infrastructure fails, SQLite would be the fallback. The `DATABASE_URL` environment variable makes switching trivial.

---

## Decision 3: API Framework — FastAPI over Flask/Express

### Context
The Intelligence API needs to serve multiple endpoints with complex Pydantic validation, handle concurrent ingest from the pipeline, and provide automatic documentation for the scoring harness.

### Options Considered

| Framework | Pros | Cons |
|-----------|------|------|
| **FastAPI** (chosen) | Automatic OpenAPI docs, native Pydantic v2 integration, async/await, fastest Python framework, scoring harness explicitly supports it | Python-only |
| Flask | Simple, widely known | No native async, manual validation, no auto-docs |
| Express (Node.js) | Fast, large ecosystem | Schema validation requires extra libs (zod, joi), no scoring harness coverage |
| Go (chi/fiber) | Very fast | Verbose validation, less ML ecosystem integration |

### Decision
FastAPI. The scoring harness has "best coverage for FastAPI" (per the challenge FAQ). More importantly, FastAPI's native Pydantic v2 integration means all 8 event types with their optional fields and literal type constraints are validated automatically at the endpoint level — no manual validation code needed.

### Where AI Helped
The AI was helpful in structuring the async SQLAlchemy + asyncpg connection pool correctly for FastAPI's async request handlers. I validated its output against the SQLAlchemy 2.0 async docs before using it.

### Trade-off Acknowledged
FastAPI's dependency injection system (`Depends()`) adds a learning curve. For a simpler project, Flask would be faster to prototype. At the scale of 40 stores sending events in real time, the async architecture of FastAPI will handle concurrent ingest significantly better than a synchronous Flask app.

---

## Summary Table

| Decision | Chosen | Runner-up | Key Reason |
|----------|--------|-----------|------------|
| Detection model | YOLOv8n | YOLOv8m | Speed vs accuracy trade-off; invest in tracking layer |
| Database | PostgreSQL | SQLite | Window functions for funnel; concurrent writes; production honesty |
| API framework | FastAPI | Flask | Scoring harness coverage; native Pydantic; async ingest |
