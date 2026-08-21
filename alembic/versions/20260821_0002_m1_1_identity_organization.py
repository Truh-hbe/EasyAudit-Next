"""Persist M1.1 identity and organization foundations.

Revision ID: 20260821_0002
Revises: 20260821_0001
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260821_0002"
down_revision: str | None = "20260821_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.CheckConstraint("name = btrim(name) AND name <> ''", name="ck_organizations_name"),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
    )
    op.create_table(
        "departments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.CheckConstraint("name = btrim(name) AND name <> ''", name="ck_departments_name"),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id <> id",
            name="ck_departments_parent",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_departments_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_departments"),
        sa.UniqueConstraint("id", "organization_id", name="uq_departments_id_organization"),
    )
    op.create_foreign_key(
        "fk_departments_parent_organization",
        "departments",
        "departments",
        ["parent_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_departments_organization_parent",
        "departments",
        ["organization_id", "parent_id"],
    )
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("primary_department_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("platform_role", sa.String(length=32), nullable=False),
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
        sa.CheckConstraint(
            "display_name = btrim(display_name) AND display_name <> ''",
            name="ck_users_display_name",
        ),
        sa.CheckConstraint(
            "platform_role IN ('system_admin', 'ordinary_user')",
            name="ck_users_platform_role",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_users_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["primary_department_id", "organization_id"],
            ["departments.id", "departments.organization_id"],
            name="fk_users_primary_department_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("id", "organization_id", name="uq_users_id_organization"),
    )
    op.create_index(
        "ix_users_organization_department",
        "users",
        ["organization_id", "primary_department_id"],
    )
    op.execute(
        """
        CREATE FUNCTION reject_department_cycle() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.parent_id IS NULL THEN
                RETURN NEW;
            END IF;

            IF EXISTS (
                WITH RECURSIVE ancestors AS (
                    SELECT id, parent_id
                    FROM departments
                    WHERE id = NEW.parent_id AND organization_id = NEW.organization_id
                    UNION ALL
                    SELECT department.id, department.parent_id
                    FROM departments AS department
                    JOIN ancestors ON department.id = ancestors.parent_id
                    WHERE department.organization_id = NEW.organization_id
                )
                SELECT 1 FROM ancestors WHERE id = NEW.id
            ) THEN
                RAISE EXCEPTION 'department hierarchy cycle'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_departments_no_cycle';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER departments_reject_cycle
        BEFORE INSERT OR UPDATE OF parent_id, organization_id ON departments
        FOR EACH ROW EXECUTE FUNCTION reject_department_cycle()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER departments_reject_cycle ON departments")
    op.execute("DROP FUNCTION reject_department_cycle()")
    op.drop_index("ix_users_organization_department", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_departments_organization_parent", table_name="departments")
    op.drop_table("departments")
    op.drop_table("organizations")
