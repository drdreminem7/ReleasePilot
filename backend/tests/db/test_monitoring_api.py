"""The API exposes real process metrics when its isolated DB is configured."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

if not os.environ.get("RELEASEPILOT_DATABASE_URL"):
    pytest.skip("run make test-db with lab", allow_module_level=True)

from releasepilot.admin import add_user, register_lab_workload  # noqa: E402
from releasepilot.api import create_app  # noqa: E402
from releasepilot.db import build_engine, session_factory  # noqa: E402


def test_api_metrics_reflect_served_requests() -> None:
    engine = build_engine()
    with TestClient(create_app(engine)) as client:
        assert client.get("/health/live").status_code == 200
        response = client.get("/metrics")
        assert response.status_code == 200
        assert b'releasepilot_http_requests_total{method="GET",status="200"}' in response.content
        assert b"releasepilot_http_request_duration_seconds_bucket" in response.content
    engine.dispose()


@pytest.mark.skipif(
    os.environ.get("RELEASEPILOT_TEST_MONITORING") != "1",
    reason="requires guarded local lab and Prometheus port-forward",
)
def test_authenticated_workload_metrics_from_live_prometheus() -> None:
    engine = build_engine()
    suffix = uuid4().hex[:12]
    with session_factory(engine)() as db:
        user = add_user(db, f"metric_viewer_{suffix}", "test-password-viewer-123", "viewer")
        workload = register_lab_workload(db)
    with TestClient(create_app(engine)) as client:
        route = f"/api/v1/workloads/{workload.id}/metrics"
        assert client.get(route, params={"metric": "scrape_up"}).status_code == 401
        login = client.post(
            "/api/v1/auth/login",
            json={"username": user.username, "password": "test-password-viewer-123"},
        )
        assert login.status_code == 200
        auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
        live = client.get(route, params={"metric": "scrape_up"}, headers=auth)
        assert live.status_code == 200, live.text
        assert live.json()["state"] == "KNOWN" and live.json()["value"] == 1.0
        assert live.json()["sample_at"] and live.json()["observed_at"]
        assert live.json()["source"] == "prometheus/releasepilot/checkout-api"
        assert live.json()["evidence_id"]
        missing = client.get(
            route, params={"metric": "request_rate", "version": "v2"}, headers=auth
        )
        assert missing.status_code == 200, missing.text
        assert missing.json()["state"] == "UNKNOWN"
        assert missing.json()["value"] is None
        assert missing.json()["error_code"] == "NO_SERIES"
        invalid = client.get(route, params={"metric": "arbitrary_promql"}, headers=auth)
        assert invalid.status_code == 422
        assert client.get(route, params={"query": "up"}, headers=auth).status_code == 422
    engine.dispose()
