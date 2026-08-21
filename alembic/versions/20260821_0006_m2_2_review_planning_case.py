"""Persist M2.2 ReviewCase planning fields and Scenario data.

Revision ID: 20260821_0006
Revises: 20260821_0005
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260821_0006"
down_revision = "20260821_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_cases",
        sa.Column("planned_start_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "review_cases",
        sa.Column("planned_end_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "review_cases",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "review_cases",
        sa.Column("fieldwork_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "review_cases",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "review_cases",
        sa.Column(
            "scenario_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "ck_review_cases_dates",
        "review_cases",
        "planned_end_at IS NULL OR planned_start_at IS NULL "
        "OR planned_end_at >= planned_start_at",
    )
    op.create_index(
        "ix_review_cases_organization_planned_end",
        "review_cases",
        ["organization_id", "planned_end_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_review_cases_organization_planned_end", table_name="review_cases")
    op.drop_constraint("ck_review_cases_dates", "review_cases", type_="check")
    op.drop_column("review_cases", "scenario_data")
    op.drop_column("review_cases", "closed_at")
    op.drop_column("review_cases", "fieldwork_completed_at")
    op.drop_column("review_cases", "started_at")
    op.drop_column("review_cases", "planned_end_at")
    op.drop_column("review_cases", "planned_start_at")
