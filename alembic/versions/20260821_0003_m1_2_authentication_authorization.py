"""Persist M1.2 credentials, server-side sessions, and platform audit events.

Revision ID: 20260821_0003
Revises: 20260821_0002
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260821_0003"
down_revision: str | None = "20260821_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "local_credentials",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("login_name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=500), nullable=False),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "login_name = lower(btrim(login_name)) AND login_name <> ''",
            name="ck_local_credentials_login_name",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_local_credentials_user_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_local_credentials"),
        sa.UniqueConstraint("login_name", name="uq_local_credentials_login_name"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("length(token_hash) = 64", name="ck_auth_sessions_token_hash"),
        sa.ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_auth_sessions_user_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        sa.UniqueConstraint("id", "organization_id", name="uq_auth_sessions_id_organization"),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index(
        "ix_auth_sessions_user_active",
        "auth_sessions",
        ["user_id", "expires_at", "revoked_at"],
    )
    op.create_table(
        "platform_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_department_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type = btrim(event_type) AND event_type <> ''",
            name="ck_audit_event_type",
        ),
        sa.CheckConstraint(
            "organization_id IS NOT NULL OR "
            "(actor_user_id IS NULL AND target_user_id IS NULL "
            "AND target_department_id IS NULL AND target_session_id IS NULL)",
            name="ck_platform_audit_typed_targets_require_organization",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_platform_audit_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_platform_audit_actor_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_platform_audit_target_user_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_department_id", "organization_id"],
            ["departments.id", "departments.organization_id"],
            name="fk_platform_audit_target_department_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_session_id", "organization_id"],
            ["auth_sessions.id", "auth_sessions.organization_id"],
            name="fk_platform_audit_target_session_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_platform_audit_events"),
    )
    op.create_index(
        "ix_platform_audit_organization_occurred",
        "platform_audit_events",
        ["organization_id", "occurred_at"],
    )
    op.execute(
        """
        CREATE FUNCTION reject_platform_audit_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'platform audit events are append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER platform_audit_events_reject_mutation
        BEFORE UPDATE OR DELETE ON platform_audit_events
        FOR EACH ROW EXECUTE FUNCTION reject_platform_audit_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER platform_audit_events_reject_mutation ON platform_audit_events")
    op.execute("DROP FUNCTION reject_platform_audit_mutation()")
    op.drop_index(
        "ix_platform_audit_organization_occurred",
        table_name="platform_audit_events",
    )
    op.drop_table("platform_audit_events")
    op.drop_index("ix_auth_sessions_user_active", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("local_credentials")
