"""Local-only, opaque bearer sessions; only token digests are persisted."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher, exceptions
from sqlalchemy import select
from sqlalchemy.orm import Session

from releasepilot.models import AuthSession, User

SESSION_HOURS = 8
hasher = PasswordHasher()


def password_hash(password: str) -> str:
    return str(hasher.hash(password))


def password_matches(stored_hash: str, password: str) -> bool:
    try:
        return bool(hasher.verify(stored_hash, password))
    except (exceptions.VerificationError, exceptions.InvalidHashError):
        return False


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: User) -> tuple[str, AuthSession]:
    token = secrets.token_urlsafe(32)
    record = AuthSession(
        user_id=user.id,
        token_digest=token_digest(token),
        expires_at=datetime.now(UTC) + timedelta(hours=SESSION_HOURS),
    )
    db.add(record)
    return token, record


def resolve_session(db: Session, token: str) -> tuple[User, AuthSession] | None:
    if not token or len(token) > 256:
        return None
    record = db.scalar(
        select(AuthSession).where(
            AuthSession.token_digest == token_digest(token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(UTC),
        )
    )
    if record is None:
        return None
    user = db.get(User, record.user_id)
    return (user, record) if user else None
