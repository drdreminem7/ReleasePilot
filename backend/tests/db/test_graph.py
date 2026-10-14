"""Fixture-provider graph run with real lab reads and PostgreSQL checkpoints."""

import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

if not os.environ.get("RELEASEPILOT_DATABASE_URL"):
    pytest.skip("run make test-db with lab", allow_module_level=True)

import releasepilot.engine as investigation_engine  # noqa: E402
from releasepilot.admin import add_user, register_lab_workload  # noqa: E402
from releasepilot.api import create_app  # noqa: E402
from releasepilot.db import build_engine, session_factory  # noqa: E402
from releasepilot.engine import process_investigation  # noqa: E402
from releasepilot.models import EvidenceItem, Investigation, InvestigationEvent  # noqa: E402
from releasepilot.worker import graph_once  # noqa: E402


def test_fixture_graph_persists_real_healthy_observations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RELEASEPILOT_PROVIDER", "fixture")
    engine = build_engine()
    factory = session_factory(engine)
    with factory() as db:
        user = add_user(db, f"graph_{uuid4().hex[:12]}", "test-graph-password-123", "operator")
        workload = register_lab_workload(db)
        item = Investigation(
            workload_id=workload.id,
            requested_by=user.id,
            idempotency_key=f"graph-{uuid4().hex}",
            correlation_id=str(uuid4()),
            status="RUNNING",
        )
        db.add(item)
        db.flush()
        db.add(
            InvestigationEvent(
                investigation_id=item.id,
                sequence=1,
                status="RUNNING",
                message="Fixture graph test started",
            )
        )
        db.commit()
        item_id = item.id
        thread_id = str(item.langgraph_thread_id)
    process_investigation(engine, item_id)
    with factory() as db:
        stored = db.get(Investigation, item_id)
        assert stored is not None
        assert stored.status == "COMPLETED", (stored.error_code, stored.summary)
        assert stored.failure_code == "HEALTHY"
        assert stored.report is not None
        assert stored.report["provider_id"] == "fixture-v1"
        evidence = db.scalars(
            select(EvidenceItem).where(EvidenceItem.investigation_id == item_id)
        ).all()
        events = db.scalars(
            select(InvestigationEvent)
            .where(InvestigationEvent.investigation_id == item_id)
            .order_by(InvestigationEvent.sequence)
        ).all()
        assert any(event.message.startswith("Graph validate_workload") for event in events)
        assert any(event.message.startswith("Graph finalize_report") for event in events)
        assert {str(item.id) for item in evidence} >= set(stored.report["supporting_evidence_ids"])
        assert any(item.type == "get_workload_status" for item in evidence)
        assert db.scalar(select(func.count()).select_from(EvidenceItem)) >= len(evidence)
        checkpoint = db.execute(
            text("SELECT count(*) FROM checkpoints WHERE thread_id = :thread_id"),
            {"thread_id": thread_id},
        ).scalar_one()
        assert checkpoint > 0
    with TestClient(create_app(engine)) as client:
        auth_response = client.post(
            "/api/v1/auth/login",
            json={"username": user.username, "password": "test-graph-password-123"},
        )
        assert auth_response.status_code == 200
        headers = {"Authorization": f"Bearer {auth_response.json()['access_token']}"}
        detail = client.get(f"/api/v1/investigations/{item_id}", headers=headers)
        evidence_response = client.get(
            f"/api/v1/investigations/{item_id}/evidence", headers=headers
        )
        assert detail.status_code == 200
        assert detail.json()["report"]["provider_id"] == "fixture-v1"
        assert evidence_response.status_code == 200
        assert len(evidence_response.json()["items"]) == len(evidence)
    engine.dispose()


@pytest.mark.skipif(
    os.environ.get("RELEASEPILOT_TEST_FAULT") != "bad-image",
    reason="run only after guarded bad-image drill",
)
def test_fixture_graph_cites_real_bad_image_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELEASEPILOT_PROVIDER", "fixture")
    engine = build_engine()
    factory = session_factory(engine)
    with factory() as db:
        user = add_user(db, f"fault_{uuid4().hex[:12]}", "test-fault-password-123", "operator")
        workload = register_lab_workload(db)
        item = Investigation(
            workload_id=workload.id,
            requested_by=user.id,
            idempotency_key=f"fault-{uuid4().hex}",
            correlation_id=str(uuid4()),
            status="RUNNING",
        )
        db.add(item)
        db.flush()
        db.add(
            InvestigationEvent(
                investigation_id=item.id,
                sequence=1,
                status="RUNNING",
                message="Fault graph test started",
            )
        )
        db.commit()
        item_id = item.id
    process_investigation(engine, item_id)
    with factory() as db:
        stored = db.get(Investigation, item_id)
        assert stored is not None
        assert stored.status == "COMPLETED", (stored.error_code, stored.summary)
        assert stored.failure_code == "IMAGE_PULL_FAILURE"
        assert stored.report is not None
        evidence = db.scalars(
            select(EvidenceItem).where(EvidenceItem.investigation_id == item_id)
        ).all()
        cited = set(stored.report["supporting_evidence_ids"])
        assert cited
        assert cited.issubset({str(item.id) for item in evidence})
        assert any(item.type == "list_workload_pods" and str(item.id) in cited for item in evidence)
        assert any(item.type == "get_pod_events" and str(item.id) in cited for item in evidence)
    engine.dispose()


def test_checkpoint_resumes_after_worker_is_killed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RELEASEPILOT_PROVIDER", "fixture")
    engine = build_engine()
    factory = session_factory(engine)
    with factory() as db:
        user = add_user(db, f"resume_{uuid4().hex[:12]}", "test-resume-password-123", "operator")
        workload = register_lab_workload(db)
        item = Investigation(
            workload_id=workload.id,
            requested_by=user.id,
            idempotency_key=f"resume-{uuid4().hex}",
            correlation_id=str(uuid4()),
            status="RUNNING",
        )
        db.add(item)
        db.flush()
        db.add(
            InvestigationEvent(
                investigation_id=item.id,
                sequence=1,
                status="RUNNING",
                message="Checkpoint resume test started",
            )
        )
        db.commit()
        item_id = item.id
    marker = tmp_path / "checkpointed"
    child = subprocess.Popen(
        [sys.executable, "tests/db/partial_worker.py", str(item_id), str(marker)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "PYTHONPATH": os.getcwd()},
    )
    try:
        deadline = time.monotonic() + 15
        while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        assert marker.exists(), "worker did not reach a durable checkpoint"
    finally:
        child.kill()
        child.wait(timeout=5)
    process_investigation(engine, item_id)
    with factory() as db:
        stored = db.get(Investigation, item_id)
        assert stored is not None
        assert stored.status == "COMPLETED", (stored.error_code, stored.summary)
        evidence = db.scalars(
            select(EvidenceItem).where(EvidenceItem.investigation_id == item_id)
        ).all()
        assert len(evidence) == 2
    engine.dispose()


def test_missing_gemini_key_escalates_without_fabricated_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RELEASEPILOT_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    engine = build_engine()
    factory = session_factory(engine)
    with factory() as db:
        user = add_user(db, f"nokey_{uuid4().hex[:12]}", "test-nokey-password-123", "operator")
        workload = register_lab_workload(db)
        item = Investigation(
            workload_id=workload.id,
            requested_by=user.id,
            idempotency_key=f"nokey-{uuid4().hex}",
            correlation_id=str(uuid4()),
            status="RUNNING",
        )
        db.add(item)
        db.flush()
        db.commit()
        item_id = item.id
    process_investigation(engine, item_id)
    with factory() as db:
        stored = db.get(Investigation, item_id)
        assert stored is not None
        assert stored.status == "ESCALATED"
        assert stored.error_code == "PROVIDER_UNAVAILABLE"
        assert stored.report is None
        assert stored.failure_code is None
        assert (
            db.scalar(
                select(func.count())
                .select_from(EvidenceItem)
                .where(EvidenceItem.investigation_id == item_id)
            )
            == 0
        )
    engine.dispose()


def test_graph_worker_claims_queued_investigation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELEASEPILOT_PROVIDER", "fixture")
    engine = build_engine()
    factory = session_factory(engine)
    with factory() as db:
        user = add_user(db, f"queue_{uuid4().hex[:12]}", "test-queue-password-123", "operator")
        workload = register_lab_workload(db)
        item = Investigation(
            workload_id=workload.id,
            requested_by=user.id,
            idempotency_key=f"queue-{uuid4().hex}",
            correlation_id=str(uuid4()),
            status="QUEUED",
        )
        db.add(item)
        db.flush()
        db.add(
            InvestigationEvent(
                investigation_id=item.id,
                sequence=1,
                status="QUEUED",
                message="Worker queue test started",
            )
        )
        db.commit()
        item_id = item.id
    with factory() as db:
        queued = db.scalar(
            select(func.count()).select_from(Investigation).where(Investigation.status == "QUEUED")
        )
    assert queued is not None
    for _ in range(queued + 1):
        assert graph_once(engine)
        with factory() as db:
            stored = db.get(Investigation, item_id)
            assert stored is not None
            if stored.status != "QUEUED":
                break
    assert stored.status == "COMPLETED", (stored.error_code, stored.summary)
    assert stored.report is not None and stored.report["provider_id"] == "fixture-v1"
    engine.dispose()


def test_completed_checkpoint_survives_projection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELEASEPILOT_PROVIDER", "fixture")
    engine = build_engine()
    factory = session_factory(engine)
    with factory() as db:
        user = add_user(db, f"project_{uuid4().hex[:12]}", "test-project-password-123", "operator")
        workload = register_lab_workload(db)
        item = Investigation(
            workload_id=workload.id,
            requested_by=user.id,
            idempotency_key=f"project-{uuid4().hex}",
            correlation_id=str(uuid4()),
            status="RUNNING",
        )
        db.add(item)
        db.flush()
        db.commit()
        item_id = item.id
        thread_id = str(item.langgraph_thread_id)

    original_project = investigation_engine._project

    def fail_projection(*args: object) -> None:
        raise RuntimeError("fixture: projection storage unavailable")

    monkeypatch.setattr(investigation_engine, "_project", fail_projection)
    with pytest.raises(RuntimeError, match="projection storage unavailable"):
        process_investigation(engine, item_id)
    monkeypatch.setattr(investigation_engine, "_project", original_project)
    with factory() as db:
        stored = db.get(Investigation, item_id)
        assert stored is not None and stored.status == "RUNNING"
        assert (
            db.execute(
                text("SELECT count(*) FROM checkpoints WHERE thread_id = :thread_id"),
                {"thread_id": thread_id},
            ).scalar_one()
            > 0
        )
    monkeypatch.setenv("RELEASEPILOT_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    def unavailable_tools(*args: object) -> None:
        raise AssertionError("completed checkpoint must not read Kubernetes again")

    monkeypatch.setattr(investigation_engine, "ReadOnlyTools", unavailable_tools)
    process_investigation(engine, item_id)
    with factory() as db:
        stored = db.get(Investigation, item_id)
        assert stored is not None and stored.status == "COMPLETED"
        assert stored.report is not None
        assert stored.report["provider_id"] == "fixture-v1"
    engine.dispose()
