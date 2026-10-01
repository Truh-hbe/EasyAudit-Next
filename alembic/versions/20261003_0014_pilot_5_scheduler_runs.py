"""Add scheduler_runs, the operational record of externally scheduled job executions.

Revision ID: 20261003_0014
Revises: 20261002_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261003_0014"
down_revision: str | None = "20261002_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduler_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_key", sa.String(length=64), nullable=False),
        sa.Column("occurrence_key", sa.String(length=200), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("scanned_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deduped_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_summary", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')", name="ck_scheduler_runs_status"
        ),
        sa.CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)", name="ck_scheduler_runs_finished"
        ),
        sa.CheckConstraint(
            "scanned_count >= 0 AND created_count >= 0 AND deduped_count >= 0 "
            "AND failed_count >= 0",
            name="ck_scheduler_runs_counts",
        ),
        sa.CheckConstraint(
            "job_key = btrim(job_key) AND job_key <> '' AND "
            "occurrence_key = btrim(occurrence_key) AND occurrence_key <> ''",
            name="ck_scheduler_runs_keys",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scheduler_runs"),
    )
    op.create_index(
        "ix_scheduler_runs_job_started",
        "scheduler_runs",
        ["job_key", sa.text("started_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_scheduler_runs_job_started", table_name="scheduler_runs")
    op.drop_table("scheduler_runs")
