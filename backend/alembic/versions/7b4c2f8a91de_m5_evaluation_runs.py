"""M5 replay evaluation run metadata.

Revision ID: 7b4c2f8a91de
Revises: c93f8d16e7d6
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7b4c2f8a91de"
down_revision: str | Sequence[str] | None = "c93f8d16e7d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("scenario_id", sa.String(length=16), nullable=False),
        sa.Column("scenario_version", sa.String(length=16), nullable=False),
        sa.Column("provider_id", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("fixture_digest", sa.String(length=64), nullable=False),
        sa.Column("source_mode", sa.String(length=32), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=False),
        sa.Column("observed_artifacts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "scenario_id", name="uq_evaluation_run_scenario"),
    )


def downgrade() -> None:
    op.drop_table("evaluation_runs")
