"""Database session boundary shared by API, admin commands, and worker."""

import os
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def database_url() -> str:
    url = os.environ.get("RELEASEPILOT_DATABASE_URL")
    if not url or not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("RELEASEPILOT_DATABASE_URL must be a psycopg PostgreSQL URL")
    return url


def build_engine(url: str | None = None) -> Engine:
    return create_engine(
        url or database_url(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"connect_timeout": 3},
    )


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def sessions(engine: Engine) -> Iterator[Session]:
    factory = session_factory(engine)
    with factory() as session:
        yield session
