"""M5 evaluation run metadata persists in the isolated PostgreSQL test DB."""

import asyncio
import os
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

if not os.environ.get("RELEASEPILOT_DATABASE_URL"):
    pytest.skip("run make test-db with lab", allow_module_level=True)

from releasepilot.admin import add_user  # noqa: E402
from releasepilot.api import create_app  # noqa: E402
from releasepilot.db import build_engine, session_factory  # noqa: E402
from releasepilot.evaluation import load_catalog, persist_report, run_catalog  # noqa: E402
from releasepilot.models import EvaluationRun  # noqa: E402
from releasepilot.providers import FixtureProvider  # noqa: E402


def test_replay_metadata_persists_as_six_labeled_rows() -> None:
    catalog = load_catalog()
    report = asyncio.run(run_catalog(catalog, FixtureProvider(), "b" * 64))
    engine = build_engine()
    persist_report(engine, catalog, report)
    factory = session_factory(engine)
    with factory() as db:
        rows = db.scalars(
            select(EvaluationRun)
            .where(EvaluationRun.run_id == UUID(report["run_id"]))
            .order_by(EvaluationRun.scenario_id)
        ).all()
        assert len(rows) == 6
        assert rows[0].source_mode == "synthetic_replay"
        assert rows[0].provider_id == "fixture-v1"
        assert rows[0].observed_artifacts["pass"] is True
        assert db.scalar(
            select(func.count()).select_from(EvaluationRun).where(
                EvaluationRun.run_id == UUID(report["run_id"])
            )
        ) == 6
        user = add_user(db, f"eval_{report['run_id'][:12]}", "test-eval-password-123", "viewer")
        username = user.username
        db.commit()
    with TestClient(create_app(engine)) as client:
        assert client.get("/api/v1/evaluations").status_code == 401
        login = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": "test-eval-password-123"},
        )
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        response = client.get(
            f"/api/v1/evaluations?run_id={report['run_id']}&limit=3", headers=headers
        )
        assert response.status_code == 200
        assert response.json()["total"] == 6
        assert len(response.json()["items"]) == 3
        assert response.json()["items"][0]["source_mode"] == "synthetic_replay"
    engine.dispose()
