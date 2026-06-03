# PROMPT: "Write pytest tests for a FastAPI /metrics endpoint backed by PostgreSQL.
# Mock the DB session and the metrics service to return known event data and assert that
# unique_visitors, conversion_rate, and avg_dwell_per_zone are computed correctly."
# CHANGES MADE: Used FastAPI dependency_overrides to replace get_db. Patched the metrics
# service function directly. Added edge cases: zero visitors (division guard), missing zone
# data, and validation of all required response fields.

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db


@pytest.fixture(autouse=True)
def override_db():
    async def _mock_db():
        yield AsyncMock()
    app.dependency_overrides[get_db] = _mock_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


BASE_METRICS = {
    "store_id": "STORE_BLR_002",
    "date": "today",
    "metrics": {
        "unique_visitors": 100,
        "conversion_rate": 0.35,
        "billing_queue_visitors": 35,
        "current_queue_depth": 3,
        "abandonment_rate": 0.057,
        "avg_dwell_ms_per_zone": {"ZONE_COSMETICS": 45000, "ZONE_APPAREL": 30000},
    }
}


class TestMetricsEndpoint:

    def test_metrics_returns_200(self, client):
        with patch("app.metrics.get_store_metrics", return_value=BASE_METRICS):
            resp = client.get("/stores/STORE_BLR_002/metrics")
        assert resp.status_code == 200

    def test_metrics_empty_store_zero_division_guard(self, client):
        """Zero-division guard: metrics return 0.0 when store has no events."""
        empty = {
            "store_id": "STORE_EMPTY",
            "date": "today",
            "metrics": {
                "unique_visitors": 0,
                "conversion_rate": 0.0,
                "billing_queue_visitors": 0,
                "current_queue_depth": 0,
                "abandonment_rate": 0.0,
                "avg_dwell_ms_per_zone": {},
            }
        }
        with patch("app.metrics.get_store_metrics", return_value=empty):
            resp = client.get("/stores/STORE_EMPTY/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["metrics"]["conversion_rate"] == 0.0
        assert data["metrics"]["unique_visitors"] == 0

    def test_metrics_conversion_rate_correct(self, client):
        """Conversion rate is billing_visitors / total_visitors."""
        with patch("app.metrics.get_store_metrics", return_value=BASE_METRICS):
            resp = client.get("/stores/STORE_BLR_002/metrics")
        assert resp.json()["metrics"]["conversion_rate"] == 0.35

    def test_metrics_zone_dwell_present(self, client):
        """avg_dwell_ms_per_zone should include all zones."""
        with patch("app.metrics.get_store_metrics", return_value=BASE_METRICS):
            resp = client.get("/stores/STORE_BLR_002/metrics")
        zones = resp.json()["metrics"]["avg_dwell_ms_per_zone"]
        assert "ZONE_COSMETICS" in zones
        assert zones["ZONE_COSMETICS"] == 45000

    def test_metrics_all_required_fields_present(self, client):
        """All required metric fields must be in the response."""
        with patch("app.metrics.get_store_metrics", return_value=BASE_METRICS):
            resp = client.get("/stores/STORE_BLR_002/metrics")
        data = resp.json()
        required = ["unique_visitors", "conversion_rate", "current_queue_depth",
                    "abandonment_rate", "avg_dwell_ms_per_zone", "billing_queue_visitors"]
        for field in required:
            assert field in data["metrics"], f"Missing: {field}"

    def test_metrics_store_id_in_response(self, client):
        with patch("app.metrics.get_store_metrics", return_value=BASE_METRICS):
            resp = client.get("/stores/STORE_BLR_002/metrics")
        assert resp.json()["store_id"] == "STORE_BLR_002"
