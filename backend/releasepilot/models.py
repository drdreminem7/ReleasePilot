"""PostgreSQL domain records. Schema changes are applied only by Alembic."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('viewer', 'operator')", name="ck_users_role"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RegisteredWorkloadRecord(Base):
    __tablename__ = "registered_workloads"
    __table_args__ = (
        UniqueConstraint(
            "cluster_fingerprint", "namespace", "kind", "name", name="uq_workload_identity"
        ),
        CheckConstraint("namespace = 'releasepilot-lab'", name="ck_workload_namespace"),
        CheckConstraint("kind IN ('Deployment', 'Rollout')", name="ck_workload_kind"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    cluster_fingerprint: Mapped[str] = mapped_column(String(36))
    namespace: Mapped[str] = mapped_column(String(63))
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(63))
    uid: Mapped[str] = mapped_column(String(36))
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class Investigation(Base):
    __tablename__ = "investigations"
    __table_args__ = (
        UniqueConstraint("requested_by", "idempotency_key", name="uq_investigation_request"),
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','AWAITING_APPROVAL','VERIFYING',"
            "'COMPLETED','FAILED','CANCELLED','ESCALATED')",
            name="ck_investigation_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workload_id: Mapped[UUID] = mapped_column(ForeignKey("registered_workloads.id"))
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    trigger_type: Mapped[str] = mapped_column(String(32), default="manual")
    correlation_id: Mapped[str] = mapped_column(String(36))
    langgraph_thread_id: Mapped[UUID] = mapped_column(default=uuid4)
    status: Mapped[str] = mapped_column(String(24), default="QUEUED")
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    report: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InvestigationEvent(Base):
    __tablename__ = "investigation_events"
    __table_args__ = (UniqueConstraint("investigation_id", "sequence", name="uq_event_sequence"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    investigation_id: Mapped[UUID] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE")
    )
    sequence: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(24))
    message: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EvidenceItem(Base):
    __tablename__ = "evidence_items"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    investigation_id: Mapped[UUID] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(24))
    source: Mapped[str] = mapped_column(String(255))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resource_uid: Mapped[str] = mapped_column(String(36))
    resource_version: Mapped[str] = mapped_column(String(64))
    content_digest: Mapped[str] = mapped_column(String(64))
    content: Mapped[dict[str, object]] = mapped_column(JSON)
    truncated: Mapped[bool] = mapped_column(default=False)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (UniqueConstraint("run_id", "scenario_id", name="uq_evaluation_run_scenario"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column()
    scenario_id: Mapped[str] = mapped_column(String(16))
    scenario_version: Mapped[str] = mapped_column(String(16))
    provider_id: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(64))
    fixture_digest: Mapped[str] = mapped_column(String(64))
    source_mode: Mapped[str] = mapped_column(String(32))
    scores: Mapped[dict[str, object]] = mapped_column(JSON)
    observed_artifacts: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_type: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[UUID | None] = mapped_column(nullable=True)
    event_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[UUID | None] = mapped_column(nullable=True)
    request_id: Mapped[str] = mapped_column(String(36))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    payload: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
