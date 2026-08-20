from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import NewType

from easyaudit_next.review_core.domain.ids import (
    ActionItemId,
    ActivityId,
    DepartmentId,
    FindingId,
    OrganizationId,
    ReviewCaseId,
    ReviewPlanId,
    SubmissionId,
    UserId,
)

ScenarioKey = NewType("ScenarioKey", str)
ScenarioVersion = NewType("ScenarioVersion", int)


class PlatformRole(StrEnum):
    SYSTEM_ADMIN = "system_admin"
    ORDINARY_USER = "ordinary_user"


@dataclass(frozen=True, slots=True)
class Organization:
    id: OrganizationId
    name: str


@dataclass(frozen=True, slots=True)
class Department:
    id: DepartmentId
    organization_id: OrganizationId
    name: str


@dataclass(frozen=True, slots=True)
class User:
    id: UserId
    organization_id: OrganizationId
    department_id: DepartmentId | None
    display_name: str
    platform_role: PlatformRole


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
    id: ActivityId
    organization_id: OrganizationId
    subject: ActivitySubject
    event_type: str
    actor_id: UserId | None
    occurred_at: datetime
    metadata: dict[str, object] = field(default_factory=dict)


class SubmissionPurpose(StrEnum):
    FINDING_REPORT = "finding_report"
    RECTIFICATION = "rectification"
    VERIFICATION = "verification"
    CLOSURE = "closure"


@dataclass(frozen=True, slots=True)
class Submission:
    id: SubmissionId
    case_id: ReviewCaseId
    finding_id: FindingId | None
    purpose: SubmissionPurpose
    submitted_by: UserId
    submitted_at: datetime
    payload: dict[str, object] = field(default_factory=dict)
