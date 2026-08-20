"""Establish the migration chain without freezing premature domain tables.

Revision ID: 20260821_0001
Revises: None
Create Date: 2026-08-21
"""

from collections.abc import Sequence

revision: str = "20260821_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """M0 baseline is intentionally schema-neutral; M1 owns the first domain tables."""


def downgrade() -> None:
    """The schema-neutral baseline has nothing to remove."""
