from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import NewType
from uuid import UUID

from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.review_core.domain.ids import (
    ActionItemId,
    ActivityId,
    FindingId,
    ReviewCaseId,
)

NotificationId = NewType("NotificationId", UUID)


class NotificationKind(StrEnum):
    CASE_MEMBERSHIP_ADDED = "case_membership_added"
    FINDING_PARTICIPANT_ADDED = "finding_participant_added"
    ACTION_ASSIGNEE_ADDED = "action_assignee_added"
    FINDING_SUBMITTED_FOR_VERIFICATION = "finding_submitted_for_verification"
    MANUAL_FINDING_NUDGE = "manual_finding_nudge"
    MANUAL_ACTION_NUDGE = "manual_action_nudge"
    AUTOMATIC_CASE_REMINDER = "automatic_case_reminder"
    AUTOMATIC_ACTION_REMINDER = "automatic_action_reminder"


class NotificationSubjectKind(StrEnum):
    REVIEW_CASE = "review_case"
    FINDING = "finding"
    ACTION_ITEM = "action_item"


class NotificationOriginKind(StrEnum):
    ACTIVITY = "activity"
    AUTOMATIC_REMINDER = "automatic_reminder"


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
class ActivityNotificationOrigin:
    activity_id: ActivityId


@dataclass(frozen=True, slots=True)
class AutomaticReminderNotificationOrigin:
    stable_key: str

    def __post_init__(self) -> None:
        if not self.stable_key.strip() or self.stable_key != self.stable_key.strip():
            raise ValueError("Automatic reminder origin key must not be blank or padded")


NotificationOrigin = ActivityNotificationOrigin | AutomaticReminderNotificationOrigin


@dataclass(frozen=True, slots=True)
class NotificationDraft:
    id: NotificationId
    organization_id: OrganizationId
    recipient_user_id: UserId
    kind: NotificationKind
    origin: NotificationOrigin
    subject: NotificationSubject
    title: str
    body: str
    created_at: datetime

    @property
    def origin_activity_id(self) -> ActivityId | None:
        if isinstance(self.origin, ActivityNotificationOrigin):
            return self.origin.activity_id
        return None

    @property
    def automatic_origin_key(self) -> str | None:
        if isinstance(self.origin, AutomaticReminderNotificationOrigin):
            return self.origin.stable_key
        return None


@dataclass(frozen=True, slots=True)
class NotificationItem:
    id: NotificationId
    organization_id: OrganizationId
    recipient_user_id: UserId
    kind: NotificationKind
    origin: NotificationOrigin
    subject: NotificationSubject
    title: str
    body: str
    created_at: datetime
    read_at: datetime | None

    @property
    def origin_kind(self) -> NotificationOriginKind:
        if isinstance(self.origin, ActivityNotificationOrigin):
            return NotificationOriginKind.ACTIVITY
        return NotificationOriginKind.AUTOMATIC_REMINDER

    @property
    def origin_activity_id(self) -> ActivityId | None:
        if isinstance(self.origin, ActivityNotificationOrigin):
            return self.origin.activity_id
        return None

    @property
    def automatic_origin_key(self) -> str | None:
        if isinstance(self.origin, AutomaticReminderNotificationOrigin):
            return self.origin.stable_key
        return None


@dataclass(frozen=True, slots=True)
class NotificationInboxPage:
    items: tuple[NotificationItem, ...]
    unread_count: int
    limit: int
    offset: int
