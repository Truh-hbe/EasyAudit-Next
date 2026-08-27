"""Add typed Notification provenance for M3.4.

Revision ID: 20260827_0011
Revises: 20260827_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260827_0011"
down_revision: str | None = "20260827_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("automatic_origin_key", sa.String(length=500), nullable=True),
    )
    op.alter_column(
        "notifications",
        "origin_activity_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.drop_constraint("uq_notifications_delivery", "notifications", type_="unique")
    op.create_check_constraint(
        "ck_notifications_exactly_one_origin",
        "notifications",
        "num_nonnulls(origin_activity_id, automatic_origin_key) = 1",
    )
    op.create_check_constraint(
        "ck_notifications_automatic_origin_key",
        "notifications",
        "automatic_origin_key IS NULL OR "
        "(automatic_origin_key = btrim(automatic_origin_key) AND automatic_origin_key <> '')",
    )
    op.create_index(
        "uq_notifications_activity_delivery",
        "notifications",
        ["organization_id", "recipient_user_id", "origin_activity_id", "kind"],
        unique=True,
        postgresql_where=sa.text("origin_activity_id IS NOT NULL"),
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_notifications_automatic_delivery
        ON notifications (
            organization_id,
            recipient_user_id,
            kind,
            COALESCE(review_case_id, finding_id, action_item_id),
            automatic_origin_key
        )
        WHERE automatic_origin_key IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_notification_origin_organization()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.origin_activity_id IS NOT NULL AND NOT EXISTS (
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
        CREATE OR REPLACE FUNCTION enforce_notification_immutability()
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
                OR NEW.automatic_origin_key IS DISTINCT FROM OLD.automatic_origin_key
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


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM notifications WHERE automatic_origin_key IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'Cannot downgrade while automatic reminder rows exist';
            END IF;
        END;
        $$
        """
    )
    op.execute("DROP INDEX IF EXISTS uq_notifications_automatic_delivery")
    op.drop_index("uq_notifications_activity_delivery", table_name="notifications")
    op.drop_constraint(
        "ck_notifications_automatic_origin_key",
        "notifications",
        type_="check",
    )
    op.drop_constraint(
        "ck_notifications_exactly_one_origin",
        "notifications",
        type_="check",
    )
    op.alter_column(
        "notifications",
        "origin_activity_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_notifications_delivery",
        "notifications",
        ["organization_id", "recipient_user_id", "origin_activity_id", "kind"],
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_notification_origin_organization()
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
        CREATE OR REPLACE FUNCTION enforce_notification_immutability()
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
    op.drop_column("notifications", "automatic_origin_key")
