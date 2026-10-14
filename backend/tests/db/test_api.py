"""M3 integration tests against the isolated PostgreSQL test database and real local lab."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

if not os.environ.get("RELEASEPILOT_DATABASE_URL"):
    pytest.skip("run make test-db with lab", allow_module_level=True)

from releasepilot.admin import add_user, register_lab_workload
from releasepilot.api import create_app
from releasepilot.db import build_engine, session_factory
from releasepilot.models import AuditEvent, Investigation, InvestigationEvent, User
from releasepilot.worker import claim_one, recover_claimed, run_once


@pytest.fixture(scope="module")
def setup() -> tuple[object, str, str, str, str]:
    engine = build_engine()
    factory = session_factory(engine)
    suffix = uuid4().hex[:12]
    with factory() as db:
        operator = add_user(db, f"operator_{suffix}", "test-password-operator-123", "operator")
        viewer = add_user(db, f"viewer_{suffix}", "test-password-viewer-123", "viewer")
        workload = register_lab_workload(db)
    try:
        yield (
            engine,
            operator.username,
            viewer.username,
            str(workload.id),
            suffix,
        )
    finally:
        engine.dispose()


def login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_auth_roles_and_readiness(setup: tuple[object, str, str, str, str]) -> None:
    engine, operator, viewer, workload_id, _ = setup
    with TestClient(create_app(engine)) as client:
        assert client.get("/health/live").json() == {"status": "live"}
        assert client.get("/health/ready").json() == {"status": "ready"}
        denied = client.get("/api/v1/workloads")
        assert denied.status_code == 401
        assert denied.json()["error"]["code"] == "AUTH_REQUIRED"
        invalid = client.post(
            "/api/v1/auth/login", json={"username": operator, "password": "wrong password"}
        )
        assert invalid.status_code == 401
        viewer_auth = login(client, viewer, "test-password-viewer-123")
        observed = client.get("/api/v1/workloads", headers=viewer_auth)
        assert observed.status_code == 200
        assert any(
            item["id"] == workload_id and item["observed_health"]["state"] == "READY"
            for item in observed.json()["items"]
        )
        role_denied = client.post(
            "/api/v1/investigations",
            json={"workload_id": workload_id},
            headers={**viewer_auth, "Idempotency-Key": "viewer-denied-key"},
        )
        assert role_denied.status_code == 403
        assert role_denied.json()["error"]["code"] == "OPERATOR_REQUIRED"
        assert client.post("/api/v1/auth/logout", headers=viewer_auth).status_code == 204
        assert client.get("/api/v1/workloads", headers=viewer_auth).status_code == 401


def test_create_duplicate_invalid_pagination_restart_worker(
    setup: tuple[object, str, str, str, str],
) -> None:
    engine, operator, _, workload_id, suffix = setup
    with TestClient(create_app(engine)) as client:
        auth = login(client, operator, "test-password-operator-123")
        bad = client.post(
            "/api/v1/investigations",
            json={"workload_id": workload_id},
            headers=auth,
        )
        assert bad.status_code == 422
        invalid = client.post(
            "/api/v1/investigations",
            json={"workload_id": "not-a-uuid"},
            headers={**auth, "Idempotency-Key": f"key-{suffix}-bad"},
        )
        assert invalid.status_code == 422
        headers = {**auth, "Idempotency-Key": f"key-{suffix}-first"}
        created = client.post(
            "/api/v1/investigations", json={"workload_id": workload_id}, headers=headers
        )
        assert created.status_code == 202, created.text
        investigation_id = created.json()["id"]
        assert created.json()["status"] == "QUEUED"
        assert created.headers["X-Request-ID"] == created.json()["correlation_id"]
        duplicate = client.post(
            "/api/v1/investigations", json={"workload_id": workload_id}, headers=headers
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "DUPLICATE_REQUEST"
        for index in range(2):
            more = client.post(
                "/api/v1/investigations",
                json={"workload_id": workload_id},
                headers={**auth, "Idempotency-Key": f"key-{suffix}-page-{index}"},
            )
            assert more.status_code == 202
        first = client.get("/api/v1/investigations?limit=2&offset=0", headers=auth)
        second = client.get("/api/v1/investigations?limit=2&offset=2", headers=auth)
        assert first.status_code == second.status_code == 200
        assert first.json()["total"] >= 3
        assert len(first.json()["items"]) == 2
        assert {item["id"] for item in first.json()["items"]}.isdisjoint(
            {item["id"] for item in second.json()["items"]}
        )
        assert client.get("/api/v1/investigations?limit=101", headers=auth).status_code == 422

    # A new ASGI application and session factory see the committed investigation.
    with TestClient(create_app(engine)) as restarted:
        auth = login(restarted, operator, "test-password-operator-123")
        detail = restarted.get(f"/api/v1/investigations/{investigation_id}", headers=auth)
        assert detail.status_code == 200
        assert detail.json()["status"] == "QUEUED"
        factory = session_factory(engine)
        with factory() as db:
            queued_count = db.scalar(
                select(func.count())
                .select_from(Investigation)
                .where(Investigation.status == "QUEUED")
            )
        assert queued_count is not None and queued_count > 0
        for _ in range(queued_count):
            assert run_once(engine)
        detail = restarted.get(f"/api/v1/investigations/{investigation_id}", headers=auth)
        assert detail.json()["status"] == "ESCALATED"
        assert detail.json()["error_code"] == "ENGINE_NOT_CONFIGURED"
        events = restarted.get(f"/api/v1/investigations/{investigation_id}/events", headers=auth)
        assert [item["status"] for item in events.json()["items"]] == [
            "QUEUED",
            "RUNNING",
            "ESCALATED",
        ]
        audit = restarted.get("/api/v1/audits?limit=100", headers=auth)
        assert audit.status_code == 200
        assert any(item["target_id"] == investigation_id for item in audit.json()["items"])
        assert not any("test-password" in str(item) for item in audit.json()["items"])


def test_concurrent_idempotency_and_recovery(setup: tuple[object, str, str, str, str]) -> None:
    engine, operator, _, workload_id, suffix = setup
    app = create_app(engine)
    with TestClient(app) as client:
        auth = login(client, operator, "test-password-operator-123")

        def submit(_: int) -> int:
            response = client.post(
                "/api/v1/investigations",
                json={"workload_id": workload_id},
                headers={**auth, "Idempotency-Key": f"key-{suffix}-concurrent"},
            )
            return response.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = sorted(pool.map(submit, range(2)))
        assert statuses == [202, 409]
        factory = session_factory(engine)
        with factory() as db:
            user = db.scalar(select(User).where(User.username == operator))
            assert user is not None
            count = db.scalar(
                select(func.count())
                .select_from(Investigation)
                .where(
                    Investigation.requested_by == user.id,
                    Investigation.idempotency_key == f"key-{suffix}-concurrent",
                )
            )
            assert count == 1
        item_id = claim_one(engine)
        assert item_id is not None
        assert recover_claimed(engine) >= 1
        with factory() as db:
            item = db.get(Investigation, item_id)
            assert item is not None and item.status == "ESCALATED"


def test_transaction_failure_rolls_back(
    setup: tuple[object, str, str, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, operator, _, workload_id, suffix = setup
    with TestClient(create_app(engine)) as client:
        auth = login(client, operator, "test-password-operator-123")
        original_commit = Session.commit

        def fail_commit(self: Session) -> None:
            raise OperationalError("simulated commit failure", {}, Exception("fixture"))

        monkeypatch.setattr(Session, "commit", fail_commit)
        try:
            failed = client.post(
                "/api/v1/investigations",
                json={"workload_id": workload_id},
                headers={**auth, "Idempotency-Key": f"key-{suffix}-rollback"},
            )
        finally:
            monkeypatch.setattr(Session, "commit", original_commit)
        assert failed.status_code == 503
        assert failed.json()["error"]["code"] == "DATABASE_WRITE_FAILED"
        factory = session_factory(engine)
        with factory() as db:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(Investigation)
                    .where(Investigation.idempotency_key == f"key-{suffix}-rollback")
                )
                == 0
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(InvestigationEvent)
                    .where(
                        InvestigationEvent.message == "Investigation queued",
                        InvestigationEvent.investigation_id.in_(
                            select(Investigation.id).where(
                                Investigation.idempotency_key == f"key-{suffix}-rollback"
                            )
                        ),
                    )
                )
                == 0
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.event_type == "INVESTIGATION_QUEUED",
                        AuditEvent.request_id == failed.headers["X-Request-ID"],
                    )
                )
                == 0
            )
