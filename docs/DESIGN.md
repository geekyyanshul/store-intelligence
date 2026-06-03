# DESIGN.md — Store Intelligence System Architecture

## Overview

The Store Intelligence system converts raw CCTV footage into actionable retail analytics. It is split into two layers: a **Detection Pipeline** (Part A) that runs offline or in real time against video clips, and an **Intelligence API** (Part B) that stores events and answers business queries in real time.

The North Star metric is **Offline Store Conversion Rate**:

```
Conversion Rate = Visitors who completed a purchase ÷ Total unique visitors in session window
```

Every design decision is evaluated against whether it makes this metric more accurate or more actionable.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     DETECTION LAYER (Part A)                │
│                                                             │
│  CCTV Clips → YOLOv8 Detect → ByteTrack Assign ID          │
│            → Zone Classification (Shapely)                  │
│            → Staff Exclusion (colour histogram)             │
│            → Re-ID (OSNet cross-camera)                     │
│            → emit.py → POST /events/ingest                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   INTELLIGENCE LAYER (Part B)               │
│                                                             │
│  FastAPI → ingestion.py (idempotent upsert)                 │
│         → PostgreSQL (events table)                         │
│         → metrics.py (SQL aggregations)                     │
│         → funnel.py (session reconstruction)                │
│         → anomalies.py (threshold-based detection)          │
│         → health.py (stale feed + DB checks)                │
└─────────────────────────────────────────────────────────────┘
```

---

## Detection Pipeline Design

### Object Detection: YOLOv8n
YOLOv8 (nano) is used for person detection. It offers an excellent accuracy/latency trade-off for real-time CCTV processing on CPU. The `person` class (COCO class 0) is the only class used; all others are filtered out.

Confidence threshold is set at **0.5** to reduce false positives (trolleys, mannequins) while retaining detections of partially occluded persons.

### Tracking: ByteTrack
ByteTrack is integrated via Ultralytics' built-in tracker. It uses a two-stage matching strategy:
1. **High-confidence detections** are matched first using IoU.
2. **Low-confidence detections** (0.1–0.5) are matched to unconfirmed tracks using a secondary association step.

This makes it robust to brief occlusions — critical in a retail environment where shelves and other customers frequently block the camera view.

### Zone Classification: Shapely
Each zone's physical boundary is described as a polygon in `store_layout.json`. A person is considered to be "in a zone" when their bounding box centroid falls within the polygon. Shapely's `Point.within(Polygon)` is used for this check on every frame.

`ZONE_DWELL` is emitted only when a visitor has been within a zone continuously for more than **3000ms (3 seconds)** to avoid noise from brief pass-throughs.

### Staff Exclusion
Staff are identified using a colour histogram approach on the top third of the bounding box (torso region):
- A reference histogram is built from a small set of manually annotated staff uniform samples.
- At inference time, the Bhattacharyya distance between the detected person's histogram and the staff reference is computed.
- If distance < 0.3, `is_staff = true` is set and the person is excluded from visitor counts.

This is a heuristic — it works for consistent uniform colours (e.g. red/blue polo shirts) but would fail for stores with inconsistent dress codes.

### Re-Entry and Cross-Camera Re-ID
A lightweight re-identification step using appearance embeddings (OSNet) is run when a tracked ID is lost. If a new tracklet appears within 30 seconds with a cosine similarity > 0.7 to a recently-lost track embedding, a `REENTRY` event is emitted and the same `visitor_id` is reused.

---

## API Design

### Database Schema
Two tables are used:

**`events`**
```sql
event_id    TEXT PRIMARY KEY,  -- idempotency key
store_id    TEXT,
camera_id   TEXT,
visitor_id  TEXT,
event_type  TEXT,
timestamp   TIMESTAMPTZ,
zone_id     TEXT,
dwell_ms    INTEGER,
is_staff    BOOLEAN,
confidence  FLOAT,
metadata    JSONB
```

**`camera_heartbeats`** — tracks last event time per camera for stale feed detection.

### Idempotency
`POST /events/ingest` uses PostgreSQL's `INSERT ... ON CONFLICT (event_id) DO NOTHING`. This means replaying the same event batch is always safe, which is critical for pipeline restarts.

### Session Reconstruction (Funnel)
A "session" is defined as all events from the same `visitor_id` within a 2-hour rolling window. Funnel stages are:
1. `ENTRY` → visitor arrived
2. `ZONE_ENTER` (any non-billing zone) → zone explored
3. `BILLING_QUEUE_JOIN` → intent to purchase
4. `EXIT` after `BILLING_QUEUE_JOIN` (without `BILLING_QUEUE_ABANDON`) → purchase inferred

---

## AI-Assisted Decisions

### Decision 1: ByteTrack vs DeepSORT for tracking
I prompted the AI: *"Compare ByteTrack and DeepSORT for real-time multi-person tracking in a retail CCTV scenario where occlusions are frequent."*

The AI correctly identified that DeepSORT requires a Re-ID model at every step (slower), while ByteTrack delays Re-ID to the second association step. I validated this by reading the ByteTrack paper. Chose ByteTrack.

I disagreed with the AI's suggestion to use StrongSORT — while more accurate, it was too slow for real-time on CPU.

### Decision 2: Zone classification rule-based vs VLM
I prompted: *"Should I use a VLM like GPT-4V to classify which zone a person is in, or use geometric polygon intersection?"*

The AI suggested the VLM approach for accuracy. I disagreed: VLM inference latency (~500ms per frame) is incompatible with real-time processing at 25fps. Rule-based Shapely polygon intersection runs in <1ms. Chose rule-based.

### Decision 3: Anomaly detection thresholds
I prompted: *"What thresholds would you use for detecting a billing queue spike in a mid-size retail store?"*

The AI suggested a static threshold of 5 people. I modified this to use a **rolling 7-day average ± 1 standard deviation** instead, because a spike threshold should be context-aware (weekday vs weekend).

---

## Edge Cases Handled

| Edge Case | Handling |
|-----------|---------|
| Re-entry (same person leaves and re-enters) | Re-ID + REENTRY event |
| Group entry (3 people enter simultaneously) | Each tracked separately by ByteTrack |
| Staff in frame | Colour histogram exclusion, is_staff=true |
| Partial occlusion | ByteTrack low-confidence association |
| Brief camera drop | STALE_FEED health warning after 5 min |
| Replay/duplicate events | Idempotent ingest via event_id PK |
| Person in multiple zones at boundary | Centroid-based assignment to single zone |
