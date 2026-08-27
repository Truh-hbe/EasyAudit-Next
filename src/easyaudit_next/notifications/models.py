from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import NewType
from uuid import UUID

from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.review_core.domain.ids import ActionItemId, ActivityId, FindingId, ReviewCaseId

NotificationId = NewType("NotificationId", UUID)


class NotificationKind(StrEnum):
    CASE_MEMBERSHIP_ADDED = "case_membership_added"
    FINDING_PARTICIPANT_ADDED = "finding_participant_added"
    ACTION_ASSIGNEE_ADDED = "action_assignee_added"
    FINDING_SUBMITTED_FOR_VERIFICATION = "finding_submitted_for_verification"


class NotificationSubjectKind(StrEnum):
    REVIEW_CASE = "review_case"
    FINDING = "finding"
    ACTION_ITEM = "action_item"


@dataclass(frozen=True, slots=True)
class ReviewCaseNotificationSubject:
    review_case_id: ReviewCaseId


@dataclass(frozen=True, slots=True)
class FindingNotificationSubject:
    finding_id: FindingId


@dataclass(frozen=True, slots=True)
class ActionItemNotificationSubject:
    action_item_id: ActionItemId


NotificationSubject = (
    ReviewCaseNotificationSubject | FindingNotificationSubject | ActionItemNotificationSubject
)


@dataclass(frozen=True, slots=True)
class NotificationDraft:
    id: NotificationId
    organization_id: OrganizationId
    recipient_user_id: UserId
    kind: NotificationKind
    origin_activity_id: ActivityId
    subject: NotificationSubject
    title: str
    body: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class NotificationItem:
    id: NotificationId
    organization_id: OrganizationId
    recipient_user_id: UserId
    kind: NotificationKind
    origin_activity_id: ActivityId
    subject: NotificationSubject
    title: str
    body: str
    created_at: datetime
    read_at: datetime | None


@dataclass(frozen=True, slots=True)
class NotificationInboxPage:
    items: tuple[NotificationItem, ...]
    unread_count: int
    limit: int
    offset: int
