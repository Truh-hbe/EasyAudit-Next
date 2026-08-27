from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from easyaudit_next.review_core.domain.models import (
    ActionItemLifecycle,
    FindingLifecycle,
    FindingSeverity,
    ReviewCaseLifecycle,
)
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActorKind,
    PermissionSource,
)


class WorkbenchRelationship(BaseModel):
    model_config = ConfigDict(frozen=True)

    role_key: str
    actor_kind: ActorKind
    source: PermissionSource


class WorkbenchCaseResponsibility(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    title: str
    lifecycle: ReviewCaseLifecycle
    role_keys: tuple[str, ...]
    planned_end_at: datetime | None


class WorkbenchFindingResponsibility(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    case_id: UUID
    title: str
    severity: FindingSeverity
    lifecycle: FindingLifecycle
    relationships: tuple[WorkbenchRelationship, ...]
    raised_at: datetime


class WorkbenchActionResponsibility(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    finding_id: UUID
    case_id: UUID
    title: str
    lifecycle: ActionItemLifecycle
    due_at: datetime | None
    relationships: tuple[WorkbenchRelationship, ...]


class WorkbenchVerificationItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    case_id: UUID
    title: str
    severity: FindingSeverity
    raised_at: datetime


class WorkbenchCaseDeadline(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    title: str
    lifecycle: ReviewCaseLifecycle
    deadline: datetime


class WorkbenchActionDeadline(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    finding_id: UUID
    case_id: UUID
    title: str
    lifecycle: ActionItemLifecycle
    deadline: datetime


class WorkbenchDeadlineBucket(BaseModel):
    model_config = ConfigDict(frozen=True)

    cases: tuple[WorkbenchCaseDeadline, ...]
    actions: tuple[WorkbenchActionDeadline, ...]


class WorkbenchResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    as_of: datetime
    case_responsibilities: tuple[WorkbenchCaseResponsibility, ...]
    finding_responsibilities: tuple[WorkbenchFindingResponsibility, ...]
    action_responsibilities: tuple[WorkbenchActionResponsibility, ...]
    verification_queue: tuple[WorkbenchVerificationItem, ...]
    due_soon: WorkbenchDeadlineBucket
    overdue: WorkbenchDeadlineBucket
