from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from easyaudit_next.review_core.domain.models import (
    ActionItemLifecycle,
    AssignmentRole,
    FindingLifecycle,
    FindingSeverity,
    ReviewCaseLifecycle,
    SubmissionPurpose,
)
from easyaudit_next.review_core.domain.scenario_capabilities import ActorKind


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


class ReviewCatalogItemResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_key: str
    scenario_version: int
    display_name: str


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


class ReviewCaseCollectionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: tuple[ReviewCaseResponse, ...]
    total: int
    limit: int
    offset: int


class CaseMemberCreateRequest(BaseModel):
    user_id: UUID
    role_key: str = Field(min_length=1, max_length=100)


class CaseMemberResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: UUID
    user_id: UUID
    role_key: str
    joined_at: datetime


class CaseMemberCandidateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    display_name: str


class ReviewCaseTransitionRequest(BaseModel):
    action: str = Field(min_length=1, max_length=100)
    reason: str | None = Field(default=None, max_length=2_000)


class FindingCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20_000)
    severity: FindingSeverity
    scenario_data: dict[str, object] = Field(default_factory=dict)


class FindingResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    organization_id: UUID
    case_id: UUID
    title: str
    description: str | None
    severity: FindingSeverity
    lifecycle: FindingLifecycle
    scenario_data: dict[str, object]
    raised_by: UUID
    raised_at: datetime


class FindingParticipantCreateRequest(BaseModel):
    actor_kind: ActorKind
    actor_id: UUID
    role_key: str = Field(min_length=1, max_length=100)


class FindingParticipantResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    finding_id: UUID
    actor_kind: ActorKind
    actor_id: UUID
    role_key: str
    assigned_at: datetime


class FindingTransitionRequest(BaseModel):
    action: str = Field(min_length=1, max_length=100)
    reason: str | None = Field(default=None, max_length=2_000)


class ActionItemCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    due_at: AwareDatetime | None = None


class ActionItemResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    organization_id: UUID
    finding_id: UUID
    title: str
    lifecycle: ActionItemLifecycle
    due_at: datetime | None
    completed_at: datetime | None


class ActionAssigneeCreateRequest(BaseModel):
    actor_kind: ActorKind
    actor_id: UUID
    role: AssignmentRole


class ActionAssigneeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_item_id: UUID
    actor_kind: ActorKind
    actor_id: UUID
    role: AssignmentRole
    assigned_at: datetime


class ActionItemTransitionRequest(BaseModel):
    action: str = Field(min_length=1, max_length=100)
    reason: str | None = Field(default=None, max_length=2_000)


class EvidenceRegisterRequest(BaseModel):
    storage_key: str = Field(min_length=1, max_length=500)
    original_name: str = Field(min_length=1, max_length=500)
    content_type: str | None = Field(default=None, min_length=1, max_length=255)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    description: str | None = Field(default=None, max_length=20_000)


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    organization_id: UUID
    action_item_id: UUID
    storage_key: str
    original_name: str
    content_type: str | None
    size_bytes: int
    sha256: str
    description: str | None
    uploaded_by: UUID
    created_at: datetime


class RectificationSubmissionRequest(BaseModel):
    action: str = Field(min_length=1, max_length=100)
    payload: dict[str, object] = Field(default_factory=dict)


class SubmissionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    organization_id: UUID
    case_id: UUID
    finding_id: UUID | None
    purpose: SubmissionPurpose
    submitted_by: UUID
    submitted_at: datetime
    payload: dict[str, object]


class RectificationSubmissionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    submission: SubmissionResponse
    finding: FindingResponse
