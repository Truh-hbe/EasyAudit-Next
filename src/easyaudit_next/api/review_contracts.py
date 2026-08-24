from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from easyaudit_next.review_core.domain.models import ReviewCaseLifecycle


class ReviewPlanCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    planned_start_at: AwareDatetime | None = None
    planned_end_at: AwareDatetime | None = None


class ReviewPlanResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    organization_id: UUID
    title: str
    planned_start_at: datetime | None
    planned_end_at: datetime | None
    created_by: UUID


class ReviewCaseCreateRequest(BaseModel):
    plan_id: UUID | None = None
    scenario_key: str = Field(min_length=1, max_length=100)
    scenario_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=300)
    planned_start_at: AwareDatetime | None = None
    planned_end_at: AwareDatetime | None = None
    scenario_data: dict[str, object] = Field(default_factory=dict)


class ReviewCaseResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    organization_id: UUID
    plan_id: UUID | None
    scenario_key: str
    scenario_version: int
    title: str
    lifecycle: ReviewCaseLifecycle
    planned_start_at: datetime | None
    planned_end_at: datetime | None
    started_at: datetime | None
    fieldwork_completed_at: datetime | None
    closed_at: datetime | None
    scenario_data: dict[str, object]
    created_by: UUID
    created_at: datetime


class CaseMemberCreateRequest(BaseModel):
    user_id: UUID
    role_key: str = Field(min_length=1, max_length=100)


class CaseMemberResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: UUID
    user_id: UUID
    role_key: str
    joined_at: datetime


class ReviewCaseTransitionRequest(BaseModel):
    action: str = Field(min_length=1, max_length=100)
    reason: str | None = Field(default=None, max_length=2_000)
