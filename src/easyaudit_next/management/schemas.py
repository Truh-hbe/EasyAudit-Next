from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from easyaudit_next.review_core.domain.models import (
    ActionItemLifecycle,
    FindingLifecycle,
    FindingSeverity,
    ReviewCaseLifecycle,
)


class DeadlineBucket(StrEnum):
    OVERDUE = "overdue"
    DUE_SOON = "due_soon"
    LATER = "later"
    NONE = "none"


class ManagementDeadlineFilter(StrEnum):
    ALL = "all"
    DUE_SOON = "due_soon"
    OVERDUE = "overdue"


class FindingLifecycleCounts(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    open: int
    rectifying: int
    verifying: int
    closed: int
    voided: int


class ActionLifecycleCounts(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    todo: int
    in_progress: int
    done: int
    cancelled: int
    overdue: int
    due_soon: int


class ManagementCaseSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    review_plan_id: UUID | None
    title: str
    scenario_key: str
    scenario_version: int
    lifecycle: ReviewCaseLifecycle
    planned_start_at: datetime | None
    planned_end_at: datetime | None
    deadline_bucket: DeadlineBucket
    findings: FindingLifecycleCounts
    actions: ActionLifecycleCounts


class ManagementCaseCollectionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    as_of: datetime
    items: tuple[ManagementCaseSummary, ...]
    total: int
    limit: int
    offset: int


class ManagementActionDeadlineItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    title: str
    lifecycle: ActionItemLifecycle
    due_at: datetime


class ManagementFindingProgress(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    title: str
    severity: FindingSeverity
    lifecycle: FindingLifecycle
    raised_at: datetime
    actions: ActionLifecycleCounts


class ManagementCaseProgressResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    as_of: datetime
    case: ManagementCaseSummary
    findings: tuple[ManagementFindingProgress, ...]
    overdue_actions: tuple[ManagementActionDeadlineItem, ...]
    due_soon_actions: tuple[ManagementActionDeadlineItem, ...]
