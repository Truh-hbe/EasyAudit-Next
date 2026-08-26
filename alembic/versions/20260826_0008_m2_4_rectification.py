"""Persist M2.4 rectification state and Evidence.

Revision ID: 20260826_0008
Revises: 20260824_0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260826_0008"
down_revision: str | None = "20260824_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "action_items",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "evidences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("original_name", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "storage_key = btrim(storage_key) AND storage_key <> ''",
            name="ck_evidences_storage_key",
        ),
        sa.CheckConstraint(
            "original_name = btrim(original_name) AND original_name <> ''",
            name="ck_evidences_original_name",
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_evidences_size_bytes"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_evidences_sha256"),
        sa.ForeignKeyConstraint(
            ["action_item_id", "organization_id"],
            ["action_items.id", "action_items.organization_id"],
            name="fk_evidences_action_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_evidences_uploader_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evidences"),
        sa.UniqueConstraint("id", "organization_id", name="uq_evidences_id_organization"),
    )
    op.create_index(
        "ix_evidences_organization_action",
        "evidences",
        ["organization_id", "action_item_id"],
    )
    op.create_index(
        "ix_evidences_organization_sha256",
        "evidences",
        ["organization_id", "sha256"],
    )

    op.execute(
        """
        CREATE FUNCTION reject_evidence_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'evidences are append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER evidences_reject_mutation
        BEFORE UPDATE OR DELETE ON evidences
        FOR EACH ROW EXECUTE FUNCTION reject_evidence_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_submission_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'submissions are append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER submissions_reject_mutation
        BEFORE UPDATE OR DELETE ON submissions
        FOR EACH ROW EXECUTE FUNCTION reject_submission_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER submissions_reject_mutation ON submissions")
    op.execute("DROP FUNCTION reject_submission_mutation()")
    op.execute("DROP TRIGGER evidences_reject_mutation ON evidences")
    op.execute("DROP FUNCTION reject_evidence_mutation()")
    op.drop_index("ix_evidences_organization_sha256", table_name="evidences")
    op.drop_index("ix_evidences_organization_action", table_name="evidences")
    op.drop_table("evidences")
    op.drop_column("action_items", "completed_at")
