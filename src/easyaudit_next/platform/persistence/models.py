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
from sqlalchemy.dialects.postgresql import JSONB
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


class LocalCredentialRecord(Base):
    __tablename__ = "local_credentials"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_local_credentials_user_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "login_name = lower(btrim(login_name)) AND login_name <> ''",
            name="ck_local_credentials_login_name",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    login_name: Mapped[str] = mapped_column(String(200), unique=True)
    password_hash: Mapped[str] = mapped_column(String(500))
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    must_change_password: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthSessionRecord(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_auth_sessions_id_organization"),
        ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_auth_sessions_user_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(token_hash) = 64", name="ck_auth_sessions_token_hash"),
        Index("ix_auth_sessions_user_active", "user_id", "expires_at", "revoked_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    user_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformAuditEventRecord(Base):
    __tablename__ = "platform_audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["actor_user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_platform_audit_actor_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["target_user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_platform_audit_target_user_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["target_department_id", "organization_id"],
            ["departments.id", "departments.organization_id"],
            name="fk_platform_audit_target_department_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["target_session_id", "organization_id"],
            ["auth_sessions.id", "auth_sessions.organization_id"],
            name="fk_platform_audit_target_session_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "event_type = btrim(event_type) AND event_type <> ''", name="ck_audit_event_type"
        ),
        CheckConstraint(
            "organization_id IS NOT NULL OR "
            "(actor_user_id IS NULL AND target_user_id IS NULL "
            "AND target_department_id IS NULL AND target_session_id IS NULL)",
            name="ck_platform_audit_typed_targets_require_organization",
        ),
        Index("ix_platform_audit_organization_occurred", "organization_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", name="fk_platform_audit_organization", ondelete="RESTRICT"),
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    target_user_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    target_department_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    target_session_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(100))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, object]] = mapped_column("metadata", JSONB, default=dict)
