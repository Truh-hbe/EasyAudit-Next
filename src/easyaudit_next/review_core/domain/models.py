from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import NewType

from easyaudit_next.platform.domain.models import Department, Organization, PlatformRole, User
from easyaudit_next.review_core.domain.ids import (
    ActionItemId,
    ActivityId,
    DepartmentId,
    FindingId,
    OrganizationId,
    ReviewCaseId,
    ReviewPlanId,
    ScenarioDefinitionId,
    ScenarioVersionId,
    SubmissionId,
    UserId,
)

__all__ = ["Department", "Organization", "PlatformRole", "User"]

ScenarioKey = NewType("ScenarioKey", str)
ScenarioVersion = NewType("ScenarioVersion", int)


@dataclass(frozen=True, slots=True)
class Scenario:
    key: ScenarioKey
    version: ScenarioVersion
    name: str
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("Scenario version must be a positive integer")


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    """Organization-specific catalog entry; behavior remains in ScenarioPolicy."""

    id: ScenarioDefinitionId
    organization_id: OrganizationId
    key: ScenarioKey
    name: str
    is_active: bool = True

    def __post_init__(self) -> None:
        if not self.key.strip() or self.key != self.key.strip():
            raise ValueError("Scenario key must not be blank or padded")
        if not self.name.strip() or self.name != self.name.strip():
            raise ValueError("Scenario name must not be blank or padded")


@dataclass(frozen=True, slots=True)
class ScenarioVersionPublication:
    """Immutable publication pointer to one code-defined ScenarioPolicy version."""

    id: ScenarioVersionId
    scenario_id: ScenarioDefinitionId
    organization_id: OrganizationId
    version: ScenarioVersion
    published_at: datetime

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("Scenario version must be a positive integer")


@dataclass(frozen=True, slots=True)
class ReviewPlan:
    """A cross-scenario planning container for a period or audit programme."""

    id: ReviewPlanId
    organization_id: OrganizationId
    title: str
    planned_start_at: datetime | None
    planned_end_at: datetime | None
    created_by: UserId


class ReviewCaseLifecycle(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    AWAITING_CLOSURE = "awaiting_closure"
    CLOSED = "closed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ReviewCase:
    id: ReviewCaseId
    organization_id: OrganizationId
    plan_id: ReviewPlanId | None
    scenario_key: ScenarioKey
    scenario_version: ScenarioVersion
    title: str
    lifecycle: ReviewCaseLifecycle
    created_by: UserId
    created_at: datetime


class FindingLifecycle(StrEnum):
    OPEN = "open"
    RECTIFYING = "rectifying"
    VERIFYING = "verifying"
    CLOSED = "closed"
    VOIDED = "voided"


class FindingSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class Finding:
    id: FindingId
    case_id: ReviewCaseId
    title: str
    description: str | None
    severity: FindingSeverity
    lifecycle: FindingLifecycle
    raised_by: UserId
    raised_at: datetime


class ActionItemLifecycle(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ActionItem:
    id: ActionItemId
    finding_id: FindingId
    title: str
    lifecycle: ActionItemLifecycle
    due_at: datetime | None


@dataclass(frozen=True, slots=True)
class UserActor:
    user_id: UserId


@dataclass(frozen=True, slots=True)
class DepartmentActor:
    department_id: DepartmentId


type ParticipantActor = UserActor | DepartmentActor


class AssignmentRole(StrEnum):
    PRIMARY = "primary"
    COLLABORATOR = "collaborator"


@dataclass(frozen=True, slots=True)
class ActionAssignee:
    action_item_id: ActionItemId
    actor: ParticipantActor
    role: AssignmentRole
    assigned_at: datetime


@dataclass(frozen=True, slots=True)
class CaseMember:
    case_id: ReviewCaseId
    user_id: UserId
    role_key: str
    joined_at: datetime


@dataclass(frozen=True, slots=True)
class FindingParticipant:
    finding_id: FindingId
    actor: ParticipantActor
    role_key: str
    assigned_at: datetime


@dataclass(frozen=True, slots=True)
class ReviewCaseActivitySubject:
    review_case_id: ReviewCaseId


@dataclass(frozen=True, slots=True)
class FindingActivitySubject:
    finding_id: FindingId


@dataclass(frozen=True, slots=True)
class ActionItemActivitySubject:
    action_item_id: ActionItemId


@dataclass(frozen=True, slots=True)
class SubmissionActivitySubject:
    submission_id: SubmissionId


type ActivitySubject = (
    ReviewCaseActivitySubject
    | FindingActivitySubject
    | ActionItemActivitySubject
    | SubmissionActivitySubject
)


@dataclass(frozen=True, slots=True)
class Activity:
    """Shallow-frozen domain fact; persistence supplies the append-only guarantee."""

    id: ActivityId
    organization_id: OrganizationId
    subject: ActivitySubject
    event_type: str
    actor_id: UserId | None
    occurred_at: datetime
    metadata: Mapping[str, object] = field(default_factory=dict)


class SubmissionPurpose(StrEnum):
    FINDING_REPORT = "finding_report"
    RECTIFICATION = "rectification"
    VERIFICATION = "verification"
    CLOSURE = "closure"


@dataclass(frozen=True, slots=True)
class Submission:
    """Shallow-frozen formal submission snapshot."""

    id: SubmissionId
    case_id: ReviewCaseId
    finding_id: FindingId | None
    purpose: SubmissionPurpose
    submitted_by: UserId
    submitted_at: datetime
    payload: Mapping[str, object] = field(default_factory=dict)
