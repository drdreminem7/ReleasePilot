"""Local operator bootstrap commands; no password is accepted on the command line."""

import argparse
import getpass
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from releasepilot.__main__ import local_inspector
from releasepilot.auth import password_hash
from releasepilot.db import build_engine, session_factory
from releasepilot.inspection import InspectionError
from releasepilot.lab_identity import LAB_NAMESPACE
from releasepilot.models import AuditEvent, RegisteredWorkloadRecord, User
from releasepilot.rollout_inspection import ROLLOUT_NAME, local_rollout_inspector


def add_user(db: Session, username: str, password: str, role: str) -> User:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", username):
        raise ValueError("username must contain 1–64 safe characters")
    if role not in {"viewer", "operator"}:
        raise ValueError("role must be viewer or operator")
    if len(password) < 12 or len(password) > 256:
        raise ValueError("password must contain 12–256 characters")
    if db.scalar(select(User.id).where(User.username == username)) is not None:
        raise ValueError("username already exists")
    user = User(username=username, password_hash=password_hash(password), role=role)
    db.add(user)
    db.flush()
    db.add(
        AuditEvent(
            actor_type="local_admin",
            actor_id=None,
            event_type="USER_CREATED",
            target_id=user.id,
            request_id="local-admin",
            payload={"role": role},
            result={"status": "created"},
        )
    )
    db.commit()
    return user


def register_lab_workload(db: Session) -> RegisteredWorkloadRecord:
    inspector = local_inspector()
    inspector.status()
    root = Path(__file__).resolve().parents[2]
    fingerprint = (root / ".releasepilot-lab" / "cluster-uid").read_text().strip()
    if not fingerprint:
        raise InspectionError("WRONG_CLUSTER", "lab fingerprint is empty")
    existing = db.scalar(
        select(RegisteredWorkloadRecord).where(
            RegisteredWorkloadRecord.cluster_fingerprint == fingerprint,
            RegisteredWorkloadRecord.namespace == LAB_NAMESPACE,
            RegisteredWorkloadRecord.kind == "Deployment",
            RegisteredWorkloadRecord.name == inspector.workload.name,
        )
    )
    if existing is not None:
        if existing.uid != inspector.workload.uid:
            raise InspectionError("STALE_WORKLOAD_UID", "registry UID differs from lab workload")
        return existing
    record = RegisteredWorkloadRecord(
        cluster_fingerprint=fingerprint,
        namespace=LAB_NAMESPACE,
        kind="Deployment",
        name=inspector.workload.name,
        uid=inspector.workload.uid,
    )
    db.add(record)
    db.flush()
    db.add(
        AuditEvent(
            actor_type="local_admin",
            actor_id=None,
            event_type="WORKLOAD_REGISTERED",
            target_id=record.id,
            request_id="local-admin",
            payload={"namespace": LAB_NAMESPACE, "kind": "Deployment"},
            result={"status": "registered"},
        )
    )
    db.commit()
    return record


def register_lab_rollout(db: Session) -> RegisteredWorkloadRecord:
    inspector = local_rollout_inspector()
    inspector.status()
    root = Path(__file__).resolve().parents[2]
    fingerprint = (root / ".releasepilot-lab" / "cluster-uid").read_text().strip()
    existing = db.scalar(
        select(RegisteredWorkloadRecord).where(
            RegisteredWorkloadRecord.cluster_fingerprint == fingerprint,
            RegisteredWorkloadRecord.namespace == LAB_NAMESPACE,
            RegisteredWorkloadRecord.kind == "Rollout",
            RegisteredWorkloadRecord.name == ROLLOUT_NAME,
        )
    )
    if existing is not None:
        if existing.uid != inspector.uid:
            raise InspectionError("STALE_WORKLOAD_UID", "registry UID differs from lab Rollout")
        return existing
    record = RegisteredWorkloadRecord(
        cluster_fingerprint=fingerprint,
        namespace=LAB_NAMESPACE,
        kind="Rollout",
        name=ROLLOUT_NAME,
        uid=inspector.uid,
    )
    db.add(record)
    db.flush()
    db.add(
        AuditEvent(
            actor_type="local_admin",
            actor_id=None,
            event_type="WORKLOAD_REGISTERED",
            target_id=record.id,
            request_id="local-admin",
            payload={"namespace": LAB_NAMESPACE, "kind": "Rollout"},
            result={"status": "registered"},
        )
    )
    db.commit()
    return record


def main() -> int:
    parser = argparse.ArgumentParser(prog="releasepilot-admin")
    commands = parser.add_subparsers(dest="command", required=True)
    user = commands.add_parser("user-add")
    user.add_argument("username")
    user.add_argument("--role", choices=["viewer", "operator"], required=True)
    commands.add_parser("register-lab")
    commands.add_parser("register-rollout")
    args = parser.parse_args()
    engine = build_engine()
    factory = session_factory(engine)
    try:
        with factory() as db:
            if args.command == "user-add":
                password = getpass.getpass("Password: ")
                repeat = getpass.getpass("Repeat password: ")
                if password != repeat:
                    raise ValueError("passwords do not match")
                created = add_user(db, args.username, password, args.role)
                print(f"Created {created.role} {created.username} ({created.id})")
            else:
                registered = (
                    register_lab_rollout(db)
                    if args.command == "register-rollout"
                    else register_lab_workload(db)
                )
                print(
                    f"Registered {registered.kind} "
                    f"{registered.namespace}/{registered.name} ({registered.id})"
                )
    except (ValueError, InspectionError) as error:
        parser.exit(1, f"{error}\n")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
