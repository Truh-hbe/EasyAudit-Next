from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from easyaudit_next.platform.domain.ids import (
    AuthSessionId,
    DepartmentId,
    OrganizationId,
    PlatformAuditEventId,
    UserId,
)


def _require_name(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    if value != value.strip():
        raise ValueError(f"{field_name} must not have leading or trailing whitespace")


class PlatformRole(StrEnum):
    SYSTEM_ADMIN = "system_admin"
    ORDINARY_USER = "ordinary_user"


@dataclass(frozen=True, slots=True)
class Organization:
    id: OrganizationId
    name: str
    is_active: bool = True

    def __post_init__(self) -> None:
        _require_name(self.name, "Organization name")


@dataclass(frozen=True, slots=True)
class Department:
    id: DepartmentId
    organization_id: OrganizationId
    name: str
    parent_id: DepartmentId | None = None
    is_active: bool = True

    def __post_init__(self) -> None:
        _require_name(self.name, "Department name")
        if self.parent_id == self.id:
            raise ValueError("Department cannot be its own parent")


@dataclass(frozen=True, slots=True)
class User:
    id: UserId
    organization_id: OrganizationId
    display_name: str
    platform_role: PlatformRole
    primary_department_id: DepartmentId | None = None
    is_active: bool = True

    def __post_init__(self) -> None:
        _require_name(self.display_name, "User display name")


@dataclass(frozen=True, slots=True)
class LocalCredential:
    user_id: UserId
    organization_id: OrganizationId
    login_name: str
    password_hash: str
    password_changed_at: datetime
    must_change_password: bool = False

    def __post_init__(self) -> None:
        if not self.login_name or self.login_name != self.login_name.strip().lower():
            raise ValueError("Login name must be non-blank, lowercase, and unpadded")
        if not self.password_hash:
            raise ValueError("Password hash must not be blank")


@dataclass(frozen=True, slots=True)
class AuthSession:
    id: AuthSessionId
    organization_id: OrganizationId
    user_id: UserId
    token_hash: str
    expires_at: datetime
    created_at: datetime
    revoked_at: datetime | None = None
    last_seen_at: datetime | None = None

    def __post_init__(self) -> None:
        if len(self.token_hash) != 64:
            raise ValueError("Session token hash must be a SHA-256 hex digest")


@dataclass(frozen=True, slots=True)
class PlatformAuditEvent:
    id: PlatformAuditEventId
    event_type: str
    occurred_at: datetime
    organization_id: OrganizationId | None = None
    actor_user_id: UserId | None = None
    target_user_id: UserId | None = None
    target_department_id: DepartmentId | None = None
    target_session_id: AuthSessionId | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_type.strip():
            raise ValueError("Audit event type must not be blank")
