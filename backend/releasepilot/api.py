"""M3 API: authenticated, persistent investigation queue with explicit refusal states."""

import re
import time
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, cast
from uuid import UUID, uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from releasepilot.__main__ import local_inspector
from releasepilot.auth import create_session, password_matches, resolve_session
from releasepilot.db import build_engine, session_factory
from releasepilot.http_metrics import HttpMetrics
from releasepilot.inspection import InspectionError, KubernetesInspector
from releasepilot.lab_identity import LAB_NAMESPACE
from releasepilot.models import (
    AuditEvent,
    AuthSession,
    EvaluationRun,
    EvidenceItem,
    Investigation,
    InvestigationEvent,
    RegisteredWorkloadRecord,
    User,
)
from releasepilot.read_tools import ReadOnlyTools
from releasepilot.rollout_inspection import ROLLOUT_NAME, RolloutInspector, local_rollout_inspector

security = HTTPBearer(auto_error=False)
_migration_config = Config()
_migration_config.set_main_option(
    "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
)
MIGRATION_HEAD = ScriptDirectory.from_config(_migration_config).get_current_head()


class APIProblem(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=256)


class InvestigationRequest(BaseModel):
    workload_id: UUID


def _request_id(request: Request) -> str:
    return str(request.state.request_id)


def _db(request: Request) -> Iterator[Session]:
    factory = request.app.state.session_factory
    with factory() as db:
        yield db


Db = Annotated[Session, Depends(_db)]


def _actor(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)], db: Db
) -> tuple[User, AuthSession]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise APIProblem(401, "AUTH_REQUIRED", "valid bearer token required")
    result = resolve_session(db, credentials.credentials)
    if result is None:
        raise APIProblem(401, "AUTH_REQUIRED", "valid bearer token required")
    return result


Actor = Annotated[tuple[User, AuthSession], Depends(_actor)]


def _operator(actor: Actor) -> User:
    user = actor[0]
    if user.role != "operator":
        raise APIProblem(403, "OPERATOR_REQUIRED", "operator role required")
    return user


Operator = Annotated[User, Depends(_operator)]


def _audit(
    db: Session,
    request: Request,
    event_type: str,
    actor_id: UUID | None,
    target_id: UUID | None,
    result: str,
) -> None:
    db.add(
        AuditEvent(
            actor_type="user" if actor_id else "anonymous",
            actor_id=actor_id,
            event_type=event_type,
            target_id=target_id,
            request_id=_request_id(request),
            payload={},
            result={"status": result},
        )
    )


def _investigation_out(item: Investigation) -> dict[str, object]:
    return {
        "id": item.id,
        "workload_id": item.workload_id,
        "trigger_type": item.trigger_type,
        "correlation_id": item.correlation_id,
        "status": item.status,
        "summary": item.summary,
        "failure_code": item.failure_code,
        "error_code": item.error_code,
        "report": item.report,
        "created_at": item.created_at,
        "started_at": item.started_at,
        "updated_at": item.updated_at,
        "completed_at": item.completed_at,
    }


def _workload_out(item: RegisteredWorkloadRecord) -> dict[str, object]:
    health: dict[str, object]
    try:
        if item.kind == "Rollout":
            evidence = _verified_rollout_inspector(item).status()
            data = cast(dict[str, object], evidence.data)
            state = "READY" if data.get("phase") == "Healthy" else "UNHEALTHY"
        else:
            inspector = _verified_inspector(item)
            evidence = inspector.status()
            data = cast(dict[str, object], evidence.data)
            if not isinstance(data, dict):
                raise InspectionError("INVALID_EVIDENCE", "status evidence was malformed")
            ready = (
                data.get("ready_replicas") == data.get("desired_replicas")
                and data.get("updated_replicas") == data.get("desired_replicas")
                and data.get("observed_generation") == data.get("generation")
            )
            pod_evidence = inspector.pods()
            if isinstance(pod_evidence.data, list):
                ready = ready and all(
                    isinstance(pod, dict) and pod.get("ready") for pod in pod_evidence.data
                )
            state = "READY" if ready else "UNHEALTHY"
        health = {
            "state": state,
            "observed_at": evidence.observed_at,
            "resource_version": evidence.resource_version,
        }
    except InspectionError as error:
        health = {"state": "UNKNOWN", "error_code": error.code}
    return {
        "id": item.id,
        "namespace": item.namespace,
        "kind": item.kind,
        "name": item.name,
        "uid": item.uid,
        "enabled": item.enabled,
        "investigation_supported": item.kind == "Deployment",
        "observed_health": health,
    }


def _verified_inspector(item: RegisteredWorkloadRecord) -> KubernetesInspector:
    inspector = local_inspector()
    root = Path(__file__).resolve().parents[2]
    fingerprint = (root / ".releasepilot-lab" / "cluster-uid").read_text().strip()
    if (
        item.cluster_fingerprint != fingerprint
        or item.namespace != LAB_NAMESPACE
        or item.kind != "Deployment"
        or item.name != inspector.workload.name
        or item.uid != inspector.workload.uid
    ):
        raise InspectionError("STALE_WORKLOAD_UID", "registered identity differs from lab")
    return inspector


def _verified_rollout_inspector(item: RegisteredWorkloadRecord) -> RolloutInspector:
    inspector = local_rollout_inspector()
    root = Path(__file__).resolve().parents[2]
    fingerprint = (root / ".releasepilot-lab" / "cluster-uid").read_text().strip()
    if (
        item.cluster_fingerprint != fingerprint
        or item.namespace != LAB_NAMESPACE
        or item.kind != "Rollout"
        or item.name != ROLLOUT_NAME
        or item.uid != inspector.uid
    ):
        raise InspectionError("STALE_WORKLOAD_UID", "registered Rollout identity differs")
    return inspector


def create_app(engine: Engine | None = None) -> FastAPI:
    app = FastAPI(title="ReleasePilot", version="0.3.0")
    app.state.engine = engine or build_engine()
    app.state.http_metrics = HttpMetrics()
    factory: sessionmaker[Session] = session_factory(app.state.engine)
    app.state.session_factory = factory

    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = uuid4()
        started = time.monotonic()
        try:
            response: Response = await call_next(request)
        except Exception:
            app.state.http_metrics.observe(request.method, 500, time.monotonic() - started)
            raise
        app.state.http_metrics.observe(
            request.method, response.status_code, time.monotonic() - started
        )
        response.headers["X-Request-ID"] = _request_id(request)
        return response

    @app.exception_handler(APIProblem)
    async def problem_handler(request: Request, error: APIProblem) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {"code": error.code, "message": error.message},
                "request_id": _request_id(request),
            },
            headers={"WWW-Authenticate": "Bearer"} if error.status_code == 401 else None,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {"code": "VALIDATION_ERROR", "message": "invalid request"},
                "request_id": _request_id(request),
            },
        )

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(
            content=app.state.http_metrics.render(),
            media_type=app.state.http_metrics.content_type,
        )

    @app.get("/health/ready")
    def ready() -> dict[str, str]:
        try:
            with app.state.engine.connect() as connection:
                version = connection.execute(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                ).scalar_one_or_none()
                if MIGRATION_HEAD is None or version != MIGRATION_HEAD:
                    raise APIProblem(503, "DATABASE_NOT_READY", "database migration is incomplete")
        except SQLAlchemyError as error:
            raise APIProblem(
                503, "DATABASE_NOT_READY", "database or migration unavailable"
            ) from error
        return {"status": "ready"}

    @app.post("/api/v1/auth/login")
    def login(
        payload: LoginRequest, request: Request, db: Db, response: Response
    ) -> dict[str, object]:
        user = db.scalar(select(User).where(User.username == payload.username))
        if user is None or not password_matches(user.password_hash, payload.password):
            _audit(db, request, "LOGIN_DENIED", None, None, "denied")
            db.commit()
            raise APIProblem(401, "INVALID_CREDENTIALS", "username or password invalid")
        token, session_record = create_session(db, user)
        db.flush()
        _audit(db, request, "LOGIN", user.id, session_record.id, "success")
        db.commit()
        response.headers["Cache-Control"] = "no-store"
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_at": session_record.expires_at,
        }

    @app.post("/api/v1/auth/logout", status_code=204)
    def logout(request: Request, db: Db, actor: Actor) -> Response:
        user, session_record = actor
        session_record.revoked_at = datetime.now(UTC)
        _audit(db, request, "LOGOUT", user.id, session_record.id, "success")
        db.commit()
        return Response(status_code=204)

    @app.get("/api/v1/workloads")
    def workloads(db: Db, actor: Actor) -> dict[str, object]:
        items = db.scalars(
            select(RegisteredWorkloadRecord)
            .where(RegisteredWorkloadRecord.enabled.is_(True))
            .order_by(RegisteredWorkloadRecord.name)
            .limit(100)
        ).all()
        return {"items": [_workload_out(item) for item in items]}

    @app.get("/api/v1/workloads/{workload_id}")
    def workload_detail(workload_id: UUID, db: Db, actor: Actor) -> dict[str, object]:
        item = db.get(RegisteredWorkloadRecord, workload_id)
        if item is None or not item.enabled:
            raise APIProblem(404, "WORKLOAD_NOT_FOUND", "registered workload not found")
        return _workload_out(item)

    @app.get("/api/v1/workloads/{workload_id}/metrics")
    def workload_metrics(
        workload_id: UUID,
        db: Db,
        actor: Actor,
        metric: Literal["scrape_up", "request_rate", "error_ratio", "latency_p95"],
        version: Literal["v1", "v2"] = "v1",
    ) -> dict[str, object]:
        item = db.get(RegisteredWorkloadRecord, workload_id)
        if item is None or not item.enabled:
            raise APIProblem(404, "WORKLOAD_NOT_FOUND", "registered workload not found")
        try:
            evidence = ReadOnlyTools(item).execute("query_workload_metric", metric, version)
        except InspectionError as error:
            raise APIProblem(503, error.code, "metric read unavailable") from error
        result = cast(dict[str, object], evidence["data"])
        return {"evidence_id": evidence["id"], **result}

    @app.get("/api/v1/workloads/{workload_id}/analysis")
    def workload_analysis(workload_id: UUID, db: Db, actor: Actor) -> dict[str, object]:
        item = db.get(RegisteredWorkloadRecord, workload_id)
        if item is None or not item.enabled:
            raise APIProblem(404, "WORKLOAD_NOT_FOUND", "registered workload not found")
        if item.kind != "Rollout":
            raise APIProblem(409, "WORKLOAD_KIND_MISMATCH", "workload is not a Rollout")
        try:
            inspector = _verified_rollout_inspector(item)
            rollout = inspector.status()
            runs = inspector.analysis()
        except InspectionError as error:
            raise APIProblem(503, error.code, "Rollout read unavailable") from error
        return {"rollout": rollout.as_dict(), "analysis_runs": runs.as_dict()}

    @app.post("/api/v1/investigations", status_code=202)
    def create_investigation(
        payload: InvestigationRequest,
        request: Request,
        db: Db,
        operator: Operator,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, object]:
        if not idempotency_key or not re.fullmatch(r"[A-Za-z0-9._:-]{8,120}", idempotency_key):
            raise APIProblem(
                422, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must be 8–120 safe characters"
            )
        workload = db.get(RegisteredWorkloadRecord, payload.workload_id)
        if workload is None or not workload.enabled:
            raise APIProblem(404, "WORKLOAD_NOT_FOUND", "registered workload not found")
        try:
            inspector = _verified_inspector(workload)
            inspector.status()
        except InspectionError as error:
            raise APIProblem(503, error.code, "workload identity cannot be verified") from error
        item = Investigation(
            workload_id=workload.id,
            requested_by=operator.id,
            idempotency_key=idempotency_key,
            correlation_id=_request_id(request),
            status="QUEUED",
        )
        try:
            db.add(item)
            db.flush()
            db.add(
                InvestigationEvent(
                    investigation_id=item.id,
                    sequence=1,
                    status="QUEUED",
                    message="Investigation queued",
                )
            )
            _audit(db, request, "INVESTIGATION_QUEUED", operator.id, item.id, "queued")
            db.commit()
        except IntegrityError as error:
            db.rollback()
            raise APIProblem(409, "DUPLICATE_REQUEST", "Idempotency-Key already used") from error
        except SQLAlchemyError as error:
            db.rollback()
            raise APIProblem(
                503, "DATABASE_WRITE_FAILED", "investigation was not queued"
            ) from error
        return _investigation_out(item)

    @app.get("/api/v1/investigations")
    def investigations(
        db: Db,
        actor: Actor,
        limit: int = 20,
        offset: int = 0,
        state: Literal["QUEUED", "RUNNING", "ESCALATED", "FAILED", "COMPLETED"] | None = None,
    ) -> dict[str, object]:
        if limit < 1 or limit > 100 or offset < 0:
            raise APIProblem(422, "INVALID_PAGE", "limit must be 1–100 and offset nonnegative")
        query = select(Investigation)
        count = select(func.count()).select_from(Investigation)
        if state:
            query = query.where(Investigation.status == state)
            count = count.where(Investigation.status == state)
        total = db.scalar(count) or 0
        items = db.scalars(
            query.order_by(Investigation.created_at.desc(), Investigation.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return {
            "items": [_investigation_out(item) for item in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @app.get("/api/v1/investigations/{investigation_id}")
    def investigation_detail(investigation_id: UUID, db: Db, actor: Actor) -> dict[str, object]:
        item = db.get(Investigation, investigation_id)
        if item is None:
            raise APIProblem(404, "INVESTIGATION_NOT_FOUND", "investigation not found")
        return _investigation_out(item)

    @app.get("/api/v1/investigations/{investigation_id}/events")
    def investigation_events(investigation_id: UUID, db: Db, actor: Actor) -> dict[str, object]:
        if db.get(Investigation, investigation_id) is None:
            raise APIProblem(404, "INVESTIGATION_NOT_FOUND", "investigation not found")
        items = db.scalars(
            select(InvestigationEvent)
            .where(InvestigationEvent.investigation_id == investigation_id)
            .order_by(InvestigationEvent.sequence)
            .limit(100)
        ).all()
        return {
            "items": [
                {
                    "sequence": item.sequence,
                    "status": item.status,
                    "message": item.message,
                    "created_at": item.created_at,
                }
                for item in items
            ]
        }

    @app.get("/api/v1/investigations/{investigation_id}/evidence")
    def investigation_evidence(investigation_id: UUID, db: Db, actor: Actor) -> dict[str, object]:
        if db.get(Investigation, investigation_id) is None:
            raise APIProblem(404, "INVESTIGATION_NOT_FOUND", "investigation not found")
        items = db.scalars(
            select(EvidenceItem)
            .where(EvidenceItem.investigation_id == investigation_id)
            .order_by(EvidenceItem.observed_at, EvidenceItem.id)
            .limit(20)
        ).all()
        return {
            "items": [
                {
                    "id": item.id,
                    "type": item.type,
                    "source": item.source,
                    "observed_at": item.observed_at,
                    "resource_uid": item.resource_uid,
                    "resource_version": item.resource_version,
                    "content_digest": item.content_digest,
                    "content": item.content,
                    "truncated": item.truncated,
                }
                for item in items
            ]
        }

    @app.get("/api/v1/evaluations")
    def evaluations(
        db: Db,
        actor: Actor,
        limit: int = 20,
        offset: int = 0,
        run_id: UUID | None = None,
    ) -> dict[str, object]:
        if limit < 1 or limit > 100 or offset < 0:
            raise APIProblem(422, "INVALID_PAGE", "limit must be 1–100 and offset nonnegative")
        query = select(EvaluationRun)
        count = select(func.count()).select_from(EvaluationRun)
        if run_id is not None:
            query = query.where(EvaluationRun.run_id == run_id)
            count = count.where(EvaluationRun.run_id == run_id)
        total = db.scalar(count) or 0
        items = db.scalars(
            query.order_by(EvaluationRun.created_at.desc(), EvaluationRun.scenario_id)
            .limit(limit)
            .offset(offset)
        ).all()
        return {
            "items": [
                {
                    "id": item.id,
                    "run_id": item.run_id,
                    "scenario_id": item.scenario_id,
                    "scenario_version": item.scenario_version,
                    "provider_id": item.provider_id,
                    "prompt_version": item.prompt_version,
                    "fixture_digest": item.fixture_digest,
                    "source_mode": item.source_mode,
                    "scores": item.scores,
                    "observed_artifacts": item.observed_artifacts,
                    "created_at": item.created_at,
                }
                for item in items
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @app.get("/api/v1/audits")
    def audits(db: Db, operator: Operator, limit: int = 20, offset: int = 0) -> dict[str, object]:
        if limit < 1 or limit > 100 or offset < 0:
            raise APIProblem(422, "INVALID_PAGE", "limit must be 1–100 and offset nonnegative")
        items = db.scalars(
            select(AuditEvent)
            .order_by(AuditEvent.recorded_at.desc(), AuditEvent.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return {
            "items": [
                {
                    "id": item.id,
                    "actor_type": item.actor_type,
                    "actor_id": item.actor_id,
                    "event_type": item.event_type,
                    "target_id": item.target_id,
                    "request_id": item.request_id,
                    "recorded_at": item.recorded_at,
                    "result": item.result,
                }
                for item in items
            ]
        }

    return app


app = create_app()
