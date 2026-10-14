"""Alembic environment; database URL comes only from the process environment."""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from releasepilot.db import database_url
from releasepilot.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", database_url().replace("%", "%%"))
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
