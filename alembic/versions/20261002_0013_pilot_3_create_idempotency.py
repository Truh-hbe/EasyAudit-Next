"""Add create_idempotency_records for ReviewPlan / ReviewCase creation.

Revision ID: 20261002_0013
Revises: 20261001_0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261002_0013"
down_revision: str | None = "20261001_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "create_idempotency_records"


def _fk(name: str, local: list[str], remote: list[str]) -> sa.ForeignKeyConstraint:
    # Deferred: the claim INSERT must not take FOR KEY SHARE on the Organization / User rows
    # before the Organization lock, which would deadlock concurrent creators (lock upgrade).
    return sa.ForeignKeyConstraint(
        local,
        remote,
        name=name,
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("review_plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("review_case_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("response_status", sa.SmallInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "organization_id",
            "actor_user_id",
            "operation",
            "idempotency_key",
            name="pk_create_idempotency_records",
        ),
        _fk(
            "fk_create_idempotency_organization",
            ["organization_id"],
            ["organizations.id"],
        ),
        _fk(
            "fk_create_idempotency_actor_organization",
            ["actor_user_id", "organization_id"],
            ["users.id", "users.organization_id"],
        ),
        _fk(
            "fk_create_idempotency_plan_organization",
            ["review_plan_id", "organization_id"],
            ["review_plans.id", "review_plans.organization_id"],
        ),
        _fk(
            "fk_create_idempotency_case_organization",
            ["review_case_id", "organization_id"],
            ["review_cases.id", "review_cases.organization_id"],
        ),
        sa.UniqueConstraint("review_plan_id", name="uq_create_idempotency_review_plan"),
        sa.UniqueConstraint("review_case_id", name="uq_create_idempotency_review_case"),
        sa.CheckConstraint(
            "idempotency_key ~ '^[\\x20-\\x7e]{1,128}$'",
            name="ck_create_idempotency_key",
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64", name="ck_create_idempotency_fingerprint"
        ),
        sa.CheckConstraint("response_status = 201", name="ck_create_idempotency_status"),
        sa.CheckConstraint(
            "(operation = 'create_review_plan' "
            "AND review_plan_id IS NOT NULL AND review_case_id IS NULL) "
            "OR (operation = 'create_review_case' "
            "AND review_case_id IS NOT NULL AND review_plan_id IS NULL)",
            name="ck_create_idempotency_resource",
        ),
    )


def downgrade() -> None:
    op.drop_table(TABLE)
