"""Durable M3 queue consumer. Until M4 it explicitly escalates without diagnosis."""

import argparse
import time
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine, select, text

from releasepilot.db import build_engine, session_factory
from releasepilot.engine import process_investigation
from releasepilot.models import AuditEvent, Investigation, InvestigationEvent


def claim_one(engine: Engine) -> UUID | None:
    factory = session_factory(engine)
    with factory.begin() as db:
        item = db.scalar(
            select(Investigation)
            .where(Investigation.status == "QUEUED")
            .order_by(Investigation.created_at, Investigation.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if item is None:
            return None
        item.status = "RUNNING"
        item.started_at = datetime.now(UTC)
        item.error_code = "ENGINE_NOT_CONFIGURED"
        db.add(
            InvestigationEvent(
                investigation_id=item.id,
                sequence=2,
                status="RUNNING",
                message="Worker claimed investigation",
            )
        )
        db.add(
            AuditEvent(
                actor_type="worker",
                actor_id=None,
                event_type="INVESTIGATION_CLAIMED",
                target_id=item.id,
                request_id=item.correlation_id,
                payload={},
                result={"status": "claimed"},
            )
        )
        return item.id


def escalate_one(engine: Engine, investigation_id: UUID) -> bool:
    factory = session_factory(engine)
    with factory.begin() as db:
        item = db.scalar(
            select(Investigation)
            .where(Investigation.id == investigation_id, Investigation.status == "RUNNING")
            .with_for_update()
        )
        if item is None or item.error_code != "ENGINE_NOT_CONFIGURED":
            return False
        item.status = "ESCALATED"
        item.summary = "Investigation engine is unavailable; no diagnosis was made."
        item.completed_at = datetime.now(UTC)
        db.add(
            InvestigationEvent(
                investigation_id=item.id,
                sequence=3,
                status="ESCALATED",
                message="Investigation engine unavailable; operator review required",
            )
        )
        db.add(
            AuditEvent(
                actor_type="worker",
                actor_id=None,
                event_type="INVESTIGATION_ESCALATED",
                target_id=item.id,
                request_id=item.correlation_id,
                payload={},
                result={"error_code": "ENGINE_NOT_CONFIGURED"},
            )
        )
        return True


def recover_claimed(engine: Engine) -> int:
    factory = session_factory(engine)
    with factory() as db:
        ids = db.scalars(
            select(Investigation.id).where(
                Investigation.status == "RUNNING",
                Investigation.error_code == "ENGINE_NOT_CONFIGURED",
            )
        ).all()
    return sum(escalate_one(engine, item_id) for item_id in ids)


def run_once(engine: Engine) -> bool:
    recover_claimed(engine)
    item_id = claim_one(engine)
    if item_id is None:
        return False
    escalate_one(engine, item_id)
    return True


def claim_for_graph(engine: Engine) -> UUID | None:
    factory = session_factory(engine)
    with factory.begin() as db:
        item = db.scalar(
            select(Investigation)
            .where(Investigation.status == "QUEUED")
            .order_by(Investigation.created_at, Investigation.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if item is None:
            return None
        item.status = "RUNNING"
        item.started_at = datetime.now(UTC)
        item.error_code = None
        db.add(
            InvestigationEvent(
                investigation_id=item.id,
                sequence=2,
                status="RUNNING",
                message="Graph worker claimed investigation",
            )
        )
        db.add(
            AuditEvent(
                actor_type="worker",
                actor_id=None,
                event_type="INVESTIGATION_CLAIMED",
                target_id=item.id,
                request_id=item.correlation_id,
                payload={},
                result={"status": "claimed"},
            )
        )
        return item.id


def graph_once(engine: Engine) -> bool:
    factory = session_factory(engine)
    with factory() as db:
        interrupted = db.scalar(
            select(Investigation.id)
            .where(Investigation.status == "RUNNING", Investigation.error_code.is_(None))
            .order_by(Investigation.started_at, Investigation.id)
            .limit(1)
        )
    investigation_id = interrupted or claim_for_graph(engine)
    if investigation_id is None:
        return False
    lock_key = int.from_bytes(investigation_id.bytes[:8], "big", signed=True)
    with engine.connect() as connection:
        acquired = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key})
        if not acquired:
            return False
        try:
            process_investigation(engine, investigation_id)
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key})
    return True


def main() -> int:
    parser = argparse.ArgumentParser(prog="releasepilot-worker")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    engine = build_engine()
    try:
        if args.once:
            graph_once(engine)
        else:
            while True:
                graph_once(engine)
                time.sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
