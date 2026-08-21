from dataclasses import dataclass
from enum import StrEnum

from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId


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
