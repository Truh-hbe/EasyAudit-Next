"""Add M3.1 Workbench reverse-lookup indexes.

Revision ID: 20260827_0009
Revises: 20260826_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0009"
down_revision: str | None = "20260826_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_finding_participants_workbench_user",
        "finding_participants",
        ["organization_id", "user_id", "finding_id"],
        unique=False,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_finding_participants_workbench_department",
        "finding_participants",
        ["organization_id", "department_id", "finding_id"],
        unique=False,
        postgresql_where=sa.text("department_id IS NOT NULL"),
    )
    op.create_index(
        "ix_action_assignees_workbench_user",
        "action_assignees",
        ["organization_id", "user_id", "action_item_id"],
        unique=False,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_action_assignees_workbench_department",
        "action_assignees",
        ["organization_id", "department_id", "action_item_id"],
        unique=False,
        postgresql_where=sa.text("department_id IS NOT NULL"),
    )
    op.create_index(
        "ix_findings_workbench_verification",
        "findings",
        ["organization_id", "lifecycle", "case_id"],
        unique=False,
        postgresql_where=sa.text("lifecycle = 'verifying'"),
    )


def downgrade() -> None:
    op.drop_index("ix_findings_workbench_verification", table_name="findings")
    op.drop_index("ix_action_assignees_workbench_department", table_name="action_assignees")
    op.drop_index("ix_action_assignees_workbench_user", table_name="action_assignees")
    op.drop_index(
        "ix_finding_participants_workbench_department",
        table_name="finding_participants",
    )
    op.drop_index("ix_finding_participants_workbench_user", table_name="finding_participants")
