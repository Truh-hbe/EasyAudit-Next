from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from easyaudit_next.infrastructure.database import Base


class OrganizationRecord(Base):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("name = btrim(name) AND name <> ''", name="ck_organizations_name"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DepartmentRecord(Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_departments_id_organization"),
        ForeignKeyConstraint(
            ["parent_id", "organization_id"],
            ["departments.id", "departments.organization_id"],
            name="fk_departments_parent_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint("name = btrim(name) AND name <> ''", name="ck_departments_name"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_departments_parent"),
        Index("ix_departments_organization_parent", "organization_id", "parent_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", name="fk_departments_organization", ondelete="RESTRICT"),
    )
    parent_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserRecord(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_users_id_organization"),
        ForeignKeyConstraint(
            ["primary_department_id", "organization_id"],
            ["departments.id", "departments.organization_id"],
            name="fk_users_primary_department_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "display_name = btrim(display_name) AND display_name <> ''",
            name="ck_users_display_name",
        ),
        CheckConstraint(
            "platform_role IN ('system_admin', 'ordinary_user')",
            name="ck_users_platform_role",
        ),
        Index("ix_users_organization_department", "organization_id", "primary_department_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", name="fk_users_organization", ondelete="RESTRICT"),
    )
    primary_department_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    display_name: Mapped[str] = mapped_column(String(200))
    platform_role: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
