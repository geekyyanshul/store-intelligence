# Store Intelligence API — Apex Retail

A containerised Store Intelligence system that processes CCTV footage to emit structured behavioural events and expose real-time analytics via a REST API.

## Quick Start

```bash
git clone <repo-url>
cd store-intelligence
docker compose up --build
```

The API will be available at **http://localhost:8000**
Interactive docs: **http://localhost:8000/docs**

## Running the Detection Pipeline

### Prerequisites
```bash
cd store-intelligence
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### Process a CCTV clip
```bash
# Process a single clip and emit events to the running API
bash pipeline/run.sh --clip data/clip1.mp4 --store STORE_BLR_002 --api http://localhost:8000

# Process all clips in a directory
bash pipeline/run.sh --dir data/ --store STORE_BLR_002 --api http://localhost:8000
```

Events are:
- Printed to stdout as JSON (one per line)
- POSTed to `POST /events/ingest` on the running API
- Also saved to `pipeline/output/events.jsonl`

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health + stale feed warnings |
| POST | `/events/ingest` | Ingest batch of up to 500 events |
| GET | `/stores/{id}/metrics` | Unique visitors, conversion rate, dwell, queue |
| GET | `/stores/{id}/funnel` | Session-based conversion funnel |
| GET | `/stores/{id}/heatmap` | Zone visit frequency + avg dwell |
| GET | `/stores/{id}/anomalies` | Active anomaly detection |

## Architecture

```
CCTV Clips → pipeline/detect.py (YOLOv8 + ByteTrack) → pipeline/emit.py → POST /events/ingest
                                                                                    ↓
                                                                             PostgreSQL DB
                                                                                    ↓
                                              GET /metrics, /funnel, /heatmap, /anomalies
```

## Running Tests

```bash
source venv/bin/activate
pytest tests/ -v --tb=short
```

## Tech Stack

- **API**: FastAPI + Uvicorn
- **Database**: PostgreSQL 15 (via SQLAlchemy + asyncpg)
- **Detection**: YOLOv8 (Ultralytics) + ByteTrack
- **Infrastructure**: Docker + Docker Compose

## Live Dashboard (Bonus)

If running the dashboard:
```bash
source venv/bin/activate
python dashboard/app.py
```
Dashboard available at **http://localhost:8501**
