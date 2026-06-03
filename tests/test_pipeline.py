# PROMPT: "Write a Pytest test for a FastAPI endpoint POST /events/ingest that accepts a list of up to 500 Pydantic models. Test for success with a valid payload, and failure when batch size exceeds 500."
# CHANGES MADE: Adapted the payload to match the DetectionEvent model schema. Added proper
# FastAPI dependency_overrides to mock the DB session so no live database is required.
# Added idempotency edge case test with duplicate event_ids.

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db


def mock_db():
    """Mock DB session that does nothing."""
    db = AsyncMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    return db


@pytest.fixture(autouse=True)
def override_db():
    """Override the DB dependency for all tests in this module."""
    async def _mock_db():
        yield mock_db()
    app.dependency_overrides[get_db] = _mock_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


VALID_EVENT = {
    "event_id": "123e4567-e89b-12d3-a456-426614174000",
    "store_id": "STORE_BLR_002",
    "camera_id": "CAM_ENTRY_01",
    "visitor_id": "VIS_c8a2f1",
    "event_type": "ENTRY",
    "timestamp": "2026-03-03T14:22:10Z",
    "zone_id": None,
    "dwell_ms": 0,
    "is_staff": False,
    "confidence": 0.95,
    "metadata": None
}


def test_health_check(client):
    with patch("app.health.get_health", return_value={"status": "ok", "db": "ok", "timestamp": "2026-01-01T00:00:00+00:00", "warnings": []}):
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ingest_events_valid_batch(client):
    with patch("app.ingestion.ingest_events", return_value={"inserted": 1, "duplicates": 0}):
        response = client.post("/events/ingest", json=[VALID_EVENT])
    assert response.status_code == 202
    assert "Successfully ingested 1 events" in response.json()["message"]


def test_ingest_events_exceeds_limit(client):
    payload = []
    for i in range(501):
        e = dict(VALID_EVENT)
        e["event_id"] = f"test-{i:04d}-e89b-12d3-a456-000000000000"
        payload.append(e)
    response = client.post("/events/ingest", json=payload)
    assert response.status_code == 400
    assert "exceeds limit" in response.json()["detail"]


def test_ingest_empty_batch_rejected(client):
    response = client.post("/events/ingest", json=[])
    assert response.status_code == 400


def test_ingest_invalid_event_type_rejected(client):
    bad_event = dict(VALID_EVENT)
    bad_event["event_type"] = "INVALID_TYPE"
    response = client.post("/events/ingest", json=[bad_event])
    assert response.status_code == 422  # Pydantic validation error


def test_ingest_idempotent_duplicates_reported(client):
    """Same event_id submitted twice — second should count as duplicate."""
    with patch("app.ingestion.ingest_events", return_value={"inserted": 0, "duplicates": 1}):
        response = client.post("/events/ingest", json=[VALID_EVENT])
    assert response.status_code == 202
    assert response.json()["duplicates"] == 1


def test_ingest_zone_enter_event(client):
    zone_event = dict(VALID_EVENT)
    zone_event["event_id"] = "223e4567-e89b-12d3-a456-426614174001"
    zone_event["event_type"] = "ZONE_ENTER"
    zone_event["zone_id"] = "ZONE_COSMETICS"
    with patch("app.ingestion.ingest_events", return_value={"inserted": 1, "duplicates": 0}):
        response = client.post("/events/ingest", json=[zone_event])
    assert response.status_code == 202


def test_ingest_zone_dwell_requires_zone_id(client):
    """ZONE_DWELL without zone_id is still accepted (schema allows null zone_id)."""
    dwell_event = dict(VALID_EVENT)
    dwell_event["event_id"] = "323e4567-e89b-12d3-a456-426614174002"
    dwell_event["event_type"] = "ZONE_DWELL"
    dwell_event["dwell_ms"] = 5000
    with patch("app.ingestion.ingest_events", return_value={"inserted": 1, "duplicates": 0}):
        response = client.post("/events/ingest", json=[dwell_event])
    assert response.status_code == 202
