from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from easyaudit_next.platform.domain.models import PlatformRole


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"]
    stage: Literal["M1.4"]


class DomainModelResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: Literal["M1.4"]
    concepts: tuple[str, ...]
    backend: Literal["Python/FastAPI"]
    next: str


class LoginRequest(BaseModel):
    login_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1_000)


class UserResponse(BaseModel):
    id: UUID
    organization_id: UUID
    display_name: str
    platform_role: PlatformRole
    primary_department_id: UUID | None
    is_active: bool


class CurrentUserResponse(UserResponse):
    must_change_password: bool


class LoginResponse(BaseModel):
    user: UserResponse
    session_id: UUID
    expires_at: datetime


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1_000)
    new_password: str = Field(min_length=1, max_length=1_000)


class SessionResponse(BaseModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    last_seen_at: datetime | None
    current: bool


class OrganizationResponse(BaseModel):
    id: UUID
    name: str
    is_active: bool


class DepartmentResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    parent_id: UUID | None
    is_active: bool


class DepartmentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: UUID | None = None


class DepartmentPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    parent_id: UUID | None = None
    is_active: bool | None = None


class UserCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    login_name: str = Field(min_length=1, max_length=200)
    initial_password: str = Field(min_length=12, max_length=1_000)
    platform_role: PlatformRole = PlatformRole.ORDINARY_USER
    primary_department_id: UUID | None = None
    must_change_password: bool = True


class UserPatchRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    platform_role: PlatformRole | None = None
    primary_department_id: UUID | None = None
    is_active: bool | None = None


class CredentialResetRequest(BaseModel):
    """Opaque reset input; the service owns the authoritative password policy."""

    temporary_password: str


class ScenarioResponse(BaseModel):
    id: UUID
    organization_id: UUID
    key: str
    name: str
    is_active: bool


class ScenarioVersionResponse(BaseModel):
    id: UUID
    scenario_id: UUID
    version: int
    published_at: datetime


class AdminScenarioVersionStatus(BaseModel):
    scenario_version: int
    published_at: datetime
    registry_present: bool
    ready: bool


class AdminScenarioStatusItem(BaseModel):
    scenario_key: str
    display_name: str
    is_active: bool
    versions: list[AdminScenarioVersionStatus]


class AdminScenarioStatusResponse(BaseModel):
    items: list[AdminScenarioStatusItem]
