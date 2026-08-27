"""Add persistent in-app Notifications for M3.2.

Revision ID: 20260827_0010
Revises: 20260827_0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260827_0010"
down_revision: str | None = "20260827_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "organizations.id",
                name="fk_notifications_organization",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("recipient_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=100), nullable=False),
        sa.Column(
            "origin_activity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "activities.id",
                name="fk_notifications_origin_activity",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("review_case_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_notifications_id_organization",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_notifications_recipient_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["review_case_id", "organization_id"],
            ["review_cases.id", "review_cases.organization_id"],
            name="fk_notifications_case_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["finding_id", "organization_id"],
            ["findings.id", "findings.organization_id"],
            name="fk_notifications_finding_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["action_item_id", "organization_id"],
            ["action_items.id", "action_items.organization_id"],
            name="fk_notifications_action_organization",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "num_nonnulls(review_case_id, finding_id, action_item_id) = 1",
            name="ck_notifications_exactly_one_subject",
        ),
        sa.CheckConstraint(
            "kind = btrim(kind) AND kind <> ''",
            name="ck_notifications_kind",
        ),
        sa.CheckConstraint(
            "title = btrim(title) AND title <> ''",
            name="ck_notifications_title",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "recipient_user_id",
            "origin_activity_id",
            "kind",
            name="uq_notifications_delivery",
        ),
    )
    op.create_index(
        "ix_notifications_inbox",
        "notifications",
        ["organization_id", "recipient_user_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_unread",
        "notifications",
        ["organization_id", "recipient_user_id", "created_at"],
        unique=False,
        postgresql_where=sa.text("read_at IS NULL"),
    )
    op.execute(
        """
        CREATE FUNCTION enforce_notification_origin_organization()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM activities
                WHERE id = NEW.origin_activity_id
                  AND organization_id = NEW.organization_id
            ) THEN
                RAISE EXCEPTION 'Notification origin Activity must belong to the same Organization'
                    USING ERRCODE = '23503';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_notifications_origin_organization
        BEFORE INSERT OR UPDATE OF organization_id, origin_activity_id ON notifications
        FOR EACH ROW EXECUTE FUNCTION enforce_notification_origin_organization()
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_notification_immutability()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Notification delivery records cannot be deleted'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
                OR NEW.recipient_user_id IS DISTINCT FROM OLD.recipient_user_id
                OR NEW.kind IS DISTINCT FROM OLD.kind
                OR NEW.origin_activity_id IS DISTINCT FROM OLD.origin_activity_id
                OR NEW.review_case_id IS DISTINCT FROM OLD.review_case_id
                OR NEW.finding_id IS DISTINCT FROM OLD.finding_id
                OR NEW.action_item_id IS DISTINCT FROM OLD.action_item_id
                OR NEW.title IS DISTINCT FROM OLD.title
                OR NEW.body IS DISTINCT FROM OLD.body
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION 'Notification delivery facts are immutable'
                    USING ERRCODE = '23514';
            END IF;

            IF OLD.read_at IS NOT NULL AND NEW.read_at IS DISTINCT FROM OLD.read_at THEN
                RAISE EXCEPTION 'Notification read_at cannot be cleared or rewritten'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_notifications_immutable
        BEFORE UPDATE OR DELETE ON notifications
        FOR EACH ROW EXECUTE FUNCTION enforce_notification_immutability()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_notifications_immutable ON notifications")
    op.execute("DROP FUNCTION IF EXISTS enforce_notification_immutability()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_notifications_origin_organization ON notifications"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_notification_origin_organization()")
    op.drop_index("ix_notifications_unread", table_name="notifications")
    op.drop_index("ix_notifications_inbox", table_name="notifications")
    op.drop_table("notifications")
