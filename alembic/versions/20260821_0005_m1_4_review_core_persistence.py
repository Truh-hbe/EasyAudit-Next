"""Persist the M1.4 Review Core foundation with organization-safe relations.

Revision ID: 20260821_0005
Revises: 20260821_0004
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260821_0005"
down_revision: str | None = "20260821_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("planned_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("planned_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("title = btrim(title) AND title <> ''", name="ck_review_plans_title"),
        sa.CheckConstraint(
            "planned_end_at IS NULL OR planned_start_at IS NULL "
            "OR planned_end_at >= planned_start_at",
            name="ck_review_plans_dates",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_review_plans_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_review_plans_creator_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_review_plans"),
        sa.UniqueConstraint("id", "organization_id", name="uq_review_plans_id_organization"),
    )
    op.create_index("ix_review_plans_organization", "review_plans", ["organization_id"])

    op.create_table(
        "review_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scenario_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("title = btrim(title) AND title <> ''", name="ck_review_cases_title"),
        sa.CheckConstraint(
            "lifecycle IN ('draft', 'scheduled', 'in_progress', "
            "'awaiting_closure', 'closed', 'cancelled')",
            name="ck_review_cases_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_review_cases_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id", "organization_id"],
            ["review_plans.id", "review_plans.organization_id"],
            name="fk_review_cases_plan_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_version_id", "organization_id"],
            ["scenario_versions.id", "scenario_versions.organization_id"],
            name="fk_review_cases_scenario_version_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_review_cases_creator_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_review_cases"),
        sa.UniqueConstraint("id", "organization_id", name="uq_review_cases_id_organization"),
    )
    op.create_index(
        "ix_review_cases_organization_lifecycle",
        "review_cases",
        ["organization_id", "lifecycle"],
    )

    op.create_table(
        "case_members",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_key", sa.String(length=100), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role_key = btrim(role_key) AND role_key <> ''",
            name="ck_case_members_role",
        ),
        sa.ForeignKeyConstraint(
            ["case_id", "organization_id"],
            ["review_cases.id", "review_cases.organization_id"],
            name="fk_case_members_case_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_case_members_user_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "case_id",
            "user_id",
            "role_key",
            name="pk_case_members",
        ),
    )
    op.create_index(
        "ix_case_members_organization_user",
        "case_members",
        ["organization_id", "user_id"],
    )

    op.create_table(
        "findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("raised_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("title = btrim(title) AND title <> ''", name="ck_findings_title"),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_findings_severity",
        ),
        sa.CheckConstraint(
            "lifecycle IN ('open', 'rectifying', 'verifying', 'closed', 'voided')",
            name="ck_findings_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["case_id", "organization_id"],
            ["review_cases.id", "review_cases.organization_id"],
            name="fk_findings_case_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["raised_by", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_findings_raiser_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_findings"),
        sa.UniqueConstraint("id", "organization_id", name="uq_findings_id_organization"),
        sa.UniqueConstraint(
            "id", "case_id", "organization_id", name="uq_findings_id_case_organization"
        ),
    )
    op.create_index(
        "ix_findings_organization_case",
        "findings",
        ["organization_id", "case_id"],
    )

    op.create_table(
        "finding_participants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("role_key", sa.String(length=100), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "num_nonnulls(user_id, department_id) = 1",
            name="ck_finding_participants_actor_xor",
        ),
        sa.CheckConstraint(
            "role_key = btrim(role_key) AND role_key <> ''",
            name="ck_finding_participants_role",
        ),
        sa.ForeignKeyConstraint(
            ["finding_id", "organization_id"],
            ["findings.id", "findings.organization_id"],
            name="fk_finding_participants_finding_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_finding_participants_user_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["department_id", "organization_id"],
            ["departments.id", "departments.organization_id"],
            name="fk_finding_participants_department_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_finding_participants"),
    )
    op.create_index(
        "uq_finding_participants_user_role",
        "finding_participants",
        ["finding_id", "user_id", "role_key"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_finding_participants_department_role",
        "finding_participants",
        ["finding_id", "department_id", "role_key"],
        unique=True,
        postgresql_where=sa.text("department_id IS NOT NULL"),
    )

    op.create_table(
        "action_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("title = btrim(title) AND title <> ''", name="ck_action_items_title"),
        sa.CheckConstraint(
            "lifecycle IN ('todo', 'in_progress', 'done', 'cancelled')",
            name="ck_action_items_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["finding_id", "organization_id"],
            ["findings.id", "findings.organization_id"],
            name="fk_action_items_finding_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_action_items"),
        sa.UniqueConstraint("id", "organization_id", name="uq_action_items_id_organization"),
    )
    op.create_index(
        "ix_action_items_organization_finding",
        "action_items",
        ["organization_id", "finding_id"],
    )

    op.create_table(
        "action_assignees",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "num_nonnulls(user_id, department_id) = 1",
            name="ck_action_assignees_actor_xor",
        ),
        sa.CheckConstraint(
            "role IN ('primary', 'collaborator')",
            name="ck_action_assignees_role",
        ),
        sa.ForeignKeyConstraint(
            ["action_item_id", "organization_id"],
            ["action_items.id", "action_items.organization_id"],
            name="fk_action_assignees_action_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_action_assignees_user_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["department_id", "organization_id"],
            ["departments.id", "departments.organization_id"],
            name="fk_action_assignees_department_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_action_assignees"),
    )
    op.create_index(
        "uq_action_assignees_user_role",
        "action_assignees",
        ["action_item_id", "user_id", "role"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_action_assignees_department_role",
        "action_assignees",
        ["action_item_id", "department_id", "role"],
        unique=True,
        postgresql_where=sa.text("department_id IS NOT NULL"),
    )

    op.create_table(
        "submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("submitted_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "purpose IN ('finding_report', 'rectification', 'verification', 'closure')",
            name="ck_submissions_purpose",
        ),
        sa.ForeignKeyConstraint(
            ["case_id", "organization_id"],
            ["review_cases.id", "review_cases.organization_id"],
            name="fk_submissions_case_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["finding_id", "case_id", "organization_id"],
            ["findings.id", "findings.case_id", "findings.organization_id"],
            name="fk_submissions_finding_case_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_submissions_submitter_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_submissions"),
        sa.UniqueConstraint("id", "organization_id", name="uq_submissions_id_organization"),
    )
    op.create_index(
        "ix_submissions_organization_case",
        "submissions",
        ["organization_id", "case_id"],
    )

    op.create_table(
        "activities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_case_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "num_nonnulls(review_case_id, finding_id, action_item_id, submission_id) = 1",
            name="ck_activities_exactly_one_target",
        ),
        sa.CheckConstraint(
            "event_type = btrim(event_type) AND event_type <> ''",
            name="ck_activities_event_type",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_activities_actor_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["review_case_id", "organization_id"],
            ["review_cases.id", "review_cases.organization_id"],
            name="fk_activities_case_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["finding_id", "organization_id"],
            ["findings.id", "findings.organization_id"],
            name="fk_activities_finding_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["action_item_id", "organization_id"],
            ["action_items.id", "action_items.organization_id"],
            name="fk_activities_action_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id", "organization_id"],
            ["submissions.id", "submissions.organization_id"],
            name="fk_activities_submission_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_activities"),
    )
    op.create_index(
        "ix_activities_organization_occurred",
        "activities",
        ["organization_id", "occurred_at"],
    )
    op.execute(
        """
        CREATE FUNCTION reject_activity_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'activities are append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER activities_reject_mutation
        BEFORE UPDATE OR DELETE ON activities
        FOR EACH ROW EXECUTE FUNCTION reject_activity_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER activities_reject_mutation ON activities")
    op.execute("DROP FUNCTION reject_activity_mutation()")
    op.drop_table("activities")
    op.drop_table("submissions")
    op.drop_table("action_assignees")
    op.drop_table("action_items")
    op.drop_table("finding_participants")
    op.drop_table("findings")
    op.drop_table("case_members")
    op.drop_table("review_cases")
    op.drop_table("review_plans")
