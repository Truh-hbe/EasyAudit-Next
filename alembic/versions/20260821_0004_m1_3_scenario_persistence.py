"""Persist M1.3 organization Scenario catalogs and immutable versions.

Revision ID: 20260821_0004
Revises: 20260821_0003
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260821_0004"
down_revision: str | None = "20260821_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scenarios",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("key = btrim(key) AND key <> ''", name="ck_scenarios_key"),
        sa.CheckConstraint("name = btrim(name) AND name <> ''", name="ck_scenarios_name"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_scenarios_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scenarios"),
        sa.UniqueConstraint("id", "organization_id", name="uq_scenarios_id_organization"),
        sa.UniqueConstraint("organization_id", "key", name="uq_scenarios_organization_key"),
    )
    op.create_index(
        "ix_scenarios_organization_active",
        "scenarios",
        ["organization_id", "is_active"],
    )
    op.create_table(
        "scenario_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("version > 0", name="ck_scenario_versions_positive"),
        sa.ForeignKeyConstraint(
            ["scenario_id", "organization_id"],
            ["scenarios.id", "scenarios.organization_id"],
            name="fk_scenario_versions_scenario_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scenario_versions"),
        sa.UniqueConstraint("id", "organization_id", name="uq_scenario_versions_id_organization"),
        sa.UniqueConstraint("scenario_id", "version", name="uq_scenario_versions_version"),
    )
    op.create_index(
        "ix_scenario_versions_organization",
        "scenario_versions",
        ["organization_id", "scenario_id"],
    )
    op.execute(
        """
        CREATE FUNCTION reject_scenario_version_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'scenario versions are immutable'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER scenario_versions_reject_mutation
        BEFORE UPDATE OR DELETE ON scenario_versions
        FOR EACH ROW EXECUTE FUNCTION reject_scenario_version_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER scenario_versions_reject_mutation ON scenario_versions")
    op.execute("DROP FUNCTION reject_scenario_version_mutation()")
    op.drop_index("ix_scenario_versions_organization", table_name="scenario_versions")
    op.drop_table("scenario_versions")
    op.drop_index("ix_scenarios_organization_active", table_name="scenarios")
    op.drop_table("scenarios")
