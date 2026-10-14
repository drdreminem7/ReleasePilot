"""Opt-in authenticated read of the real lab Rollout and AnalysisRuns."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

if not os.environ.get("RELEASEPILOT_DATABASE_URL"):
    pytest.skip("run make test-db with lab", allow_module_level=True)

from releasepilot.admin import add_user, register_lab_rollout  # noqa: E402
from releasepilot.api import create_app  # noqa: E402
from releasepilot.db import build_engine, session_factory  # noqa: E402
from releasepilot.inspection import InspectionError  # noqa: E402
from releasepilot.read_tools import ReadOnlyTools  # noqa: E402


@pytest.mark.skipif(
    os.environ.get("RELEASEPILOT_TEST_ROLLOUT") != "1",
    reason="requires completed guarded Argo drill",
)
def test_viewer_sees_real_failed_and_successful_analysis() -> None:
    engine = build_engine()
    with session_factory(engine)() as db:
        viewer = add_user(
            db, f"argo_viewer_{uuid4().hex[:12]}", "test-password-viewer-123", "viewer"
        )
        rollout = register_lab_rollout(db)
    with TestClient(create_app(engine)) as client:
        route = f"/api/v1/workloads/{rollout.id}/analysis"
        assert client.get(route).status_code == 401
        login = client.post(
            "/api/v1/auth/login",
            json={"username": viewer.username, "password": "test-password-viewer-123"},
        )
        assert login.status_code == 200
        auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
        response = client.get(route, headers=auth)
        assert response.status_code == 200, response.text
        observed = response.json()
        assert observed["rollout"]["resource_uid"] == rollout.uid
        analysis = observed["analysis_runs"]
        assert analysis["source"] == "analysisruns/releasepilot-lab/checkout-canary"
        assert observed["analysis_runs"]["observed_at"]
        phases = {item["phase"] for item in observed["analysis_runs"]["data"]}
        assert {"Successful", "Failed"} <= phases
        tool = ReadOnlyTools(rollout)
        evidence = tool.execute("get_rollout_analysis")
        assert evidence["tool"] == "get_rollout_analysis"
        assert {"Successful", "Failed"} <= {item["phase"] for item in evidence["data"]}
        with pytest.raises(InspectionError) as unavailable:
            tool.execute("get_pod_logs", "anything")
        assert unavailable.value.code == "TOOL_NOT_AVAILABLE"
        workload = client.get(f"/api/v1/workloads/{rollout.id}", headers=auth)
        assert workload.status_code == 200
        assert workload.json()["kind"] == "Rollout"
        assert workload.json()["investigation_supported"] is False
    engine.dispose()
