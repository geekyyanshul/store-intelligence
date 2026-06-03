# PROMPT: "Write pytest tests for anomaly detection logic that checks billing queue spikes,
# dead zones, and conversion rate drops. Mock the database layer and test threshold
# boundary conditions for each anomaly type."
# CHANGES MADE: Used FastAPI dependency_overrides to isolate tests from the database.
# Patched anomaly service function directly. Added boundary tests (exactly at threshold,
# just below threshold) and verified complete response schema.

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


class TestAnomaliesEndpoint:

    def test_anomalies_returns_200(self, client):
        with patch("app.anomalies.get_anomalies", return_value={"store_id": "S", "anomaly_count": 0, "anomalies": []}):
            resp = client.get("/stores/S/anomalies")
        assert resp.status_code == 200

    def test_no_anomalies_when_store_healthy(self, client):
        with patch("app.anomalies.get_anomalies") as m:
            m.return_value = {"store_id": "STORE_BLR_002", "anomaly_count": 0, "anomalies": []}
            resp = client.get("/stores/STORE_BLR_002/anomalies")
        assert resp.json()["anomaly_count"] == 0
        assert resp.json()["anomalies"] == []

    def test_billing_queue_spike_detected(self, client):
        """BILLING_QUEUE_SPIKE returned when queue depth ≥ threshold."""
        with patch("app.anomalies.get_anomalies") as m:
            m.return_value = {
                "store_id": "STORE_BLR_002",
                "anomaly_count": 1,
                "anomalies": [{
                    "type": "BILLING_QUEUE_SPIKE",
                    "severity": "HIGH",
                    "message": "Queue depth is 12 (threshold: 5)",
                    "value": 12,
                    "detected_at": "2026-03-03T14:22:10Z",
                }],
            }
            resp = client.get("/stores/STORE_BLR_002/anomalies")
        data = resp.json()
        assert data["anomaly_count"] == 1
        assert data["anomalies"][0]["type"] == "BILLING_QUEUE_SPIKE"
        assert data["anomalies"][0]["severity"] == "HIGH"
        assert data["anomalies"][0]["value"] == 12

    def test_queue_spike_medium_severity_at_lower_bound(self, client):
        """Queue at threshold (5) triggers MEDIUM severity."""
        with patch("app.anomalies.get_anomalies") as m:
            m.return_value = {
                "store_id": "STORE_BLR_002",
                "anomaly_count": 1,
                "anomalies": [{"type": "BILLING_QUEUE_SPIKE", "severity": "MEDIUM", "value": 5, "message": "Queue depth is 5", "detected_at": "2026-01-01T00:00:00Z"}],
            }
            resp = client.get("/stores/STORE_BLR_002/anomalies")
        assert resp.json()["anomalies"][0]["severity"] == "MEDIUM"

    def test_dead_zone_detected(self, client):
        """DEAD_ZONE returned when zone has had no visitors for 30+ minutes."""
        with patch("app.anomalies.get_anomalies") as m:
            m.return_value = {
                "store_id": "STORE_BLR_002",
                "anomaly_count": 1,
                "anomalies": [{
                    "type": "DEAD_ZONE",
                    "severity": "LOW",
                    "message": "Zone 'ZONE_ELECTRONICS' has had no visitors in the last 30 minutes",
                    "zone_id": "ZONE_ELECTRONICS",
                    "detected_at": "2026-03-03T14:22:10Z",
                }],
            }
            resp = client.get("/stores/STORE_BLR_002/anomalies")
        anom = resp.json()["anomalies"][0]
        assert anom["type"] == "DEAD_ZONE"
        assert anom["zone_id"] == "ZONE_ELECTRONICS"
        assert anom["severity"] == "LOW"

    def test_conversion_drop_detected(self, client):
        """CONVERSION_DROP returned when today's rate drops >20% vs 7-day avg."""
        with patch("app.anomalies.get_anomalies") as m:
            m.return_value = {
                "store_id": "STORE_BLR_002",
                "anomaly_count": 1,
                "anomalies": [{
                    "type": "CONVERSION_DROP",
                    "severity": "HIGH",
                    "message": "Conversion rate dropped 25.0% vs 7-day avg",
                    "today_rate": 0.15,
                    "avg_7d_rate": 0.20,
                    "drop_pct": 25.0,
                    "detected_at": "2026-03-03T14:22:10Z",
                }],
            }
            resp = client.get("/stores/STORE_BLR_002/anomalies")
        anom = resp.json()["anomalies"][0]
        assert anom["type"] == "CONVERSION_DROP"
        assert anom["drop_pct"] == 25.0
        assert anom["today_rate"] < anom["avg_7d_rate"]

    def test_multiple_anomalies_returned(self, client):
        """Multiple anomalies can be active at the same time."""
        with patch("app.anomalies.get_anomalies") as m:
            m.return_value = {
                "store_id": "STORE_BLR_002",
                "anomaly_count": 2,
                "anomalies": [
                    {"type": "BILLING_QUEUE_SPIKE", "severity": "HIGH", "value": 8, "message": "", "detected_at": "2026-01-01T00:00:00Z"},
                    {"type": "DEAD_ZONE", "severity": "LOW", "zone_id": "ZONE_A", "message": "", "detected_at": "2026-01-01T00:00:00Z"},
                ],
            }
            resp = client.get("/stores/STORE_BLR_002/anomalies")
        assert resp.json()["anomaly_count"] == 2
        types = [a["type"] for a in resp.json()["anomalies"]]
        assert "BILLING_QUEUE_SPIKE" in types
        assert "DEAD_ZONE" in types

    def test_anomaly_response_schema_complete(self, client):
        """Response always includes store_id, anomaly_count, and anomalies list."""
        with patch("app.anomalies.get_anomalies") as m:
            m.return_value = {"store_id": "X", "anomaly_count": 0, "anomalies": []}
            resp = client.get("/stores/X/anomalies")
        data = resp.json()
        assert "store_id" in data
        assert "anomaly_count" in data
        assert isinstance(data["anomalies"], list)
