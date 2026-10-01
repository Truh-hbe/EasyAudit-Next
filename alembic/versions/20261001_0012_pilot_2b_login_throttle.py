"""Add login_throttle, the operational counters behind login rate limiting.

Revision ID: 20261001_0012
Revises: 20260827_0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261001_0012"
down_revision: str | None = "20260827_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_throttle",
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("scope IN ('login_name', 'ip')", name="ck_login_throttle_scope"),
        sa.CheckConstraint("length(key_hash) = 64", name="ck_login_throttle_key_hash"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_login_throttle_attempt_count"),
        sa.PrimaryKeyConstraint("scope", "key_hash", "window_start", name="pk_login_throttle"),
    )
    op.create_index("ix_login_throttle_window_start", "login_throttle", ["window_start"])


def downgrade() -> None:
    op.drop_index("ix_login_throttle_window_start", table_name="login_throttle")
    op.drop_table("login_throttle")
