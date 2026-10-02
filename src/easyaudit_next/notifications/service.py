from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from easyaudit_next.notifications.copy import display_copy
from easyaudit_next.notifications.models import (
    ActionItemNotificationSubject,
    ActivityNotificationOrigin,
    AutomaticReminderNotificationOrigin,
    FindingNotificationSubject,
    NotificationDraft,
    NotificationId,
    NotificationInboxPage,
    NotificationItem,
    NotificationKind,
    NotificationOrigin,
    NotificationSubject,
    ReviewCaseNotificationSubject,
)
from easyaudit_next.notifications.persistence import (
    NotificationRecord,
    SqlAlchemyNotificationRepository,
)
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.review_core.domain.ids import ActionItemId, ActivityId, FindingId, ReviewCaseId


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    """`created` rows were inserted; `deduped` hit a unique index (ON CONFLICT DO NOTHING)."""

    created: int
    deduped: int


class NotificationService:
    """Persist delivery records and expose recipient-local inbox operations."""

    def __init__(self, repository: SqlAlchemyNotificationRepository) -> None:
        self._repository = repository

    def deliver(
        self,
        *,
        organization_id: OrganizationId,
        recipients: Iterable[UserId],
        kind: NotificationKind,
        origin_activity_id: ActivityId,
        subject: NotificationSubject,
        title: str,
        body: str,
        created_at: datetime | None = None,
    ) -> None:
        """Preserve the M3.2 Activity-backed delivery contract."""

        self._deliver(
            organization_id=organization_id,
            recipients=recipients,
            kind=kind,
            origin=ActivityNotificationOrigin(origin_activity_id),
            subject=subject,
            title=title,
            body=body,
            created_at=created_at,
        )

    def deliver_automatic(
        self,
        *,
        organization_id: OrganizationId,
        recipients: Iterable[UserId],
        kind: NotificationKind,
        automatic_origin_key: str,
        subject: NotificationSubject,
        title: str,
        body: str,
        created_at: datetime | None = None,
    ) -> DeliveryOutcome:
        """Persist a timer/policy delivery without fabricating Review Activity provenance."""

        if kind not in {
            NotificationKind.AUTOMATIC_CASE_REMINDER,
            NotificationKind.AUTOMATIC_ACTION_REMINDER,
        }:
            raise ValueError("Automatic origin is only valid for automatic reminder kinds")
        return self._deliver(
            organization_id=organization_id,
            recipients=recipients,
            kind=kind,
            origin=AutomaticReminderNotificationOrigin(automatic_origin_key),
            subject=subject,
            title=title,
            body=body,
            created_at=created_at,
        )

    def _deliver(
        self,
        *,
        organization_id: OrganizationId,
        recipients: Iterable[UserId],
        kind: NotificationKind,
        origin: NotificationOrigin,
        subject: NotificationSubject,
        title: str,
        body: str,
        created_at: datetime | None,
    ) -> DeliveryOutcome:
        now = created_at or datetime.now(UTC)
        if now.utcoffset() is None:
            raise ValueError("Notification created_at must include UTC offset")
        unique_recipients = sorted(set(recipients), key=str)
        drafts = tuple(
            NotificationDraft(
                id=NotificationId(uuid4()),
                organization_id=organization_id,
                recipient_user_id=recipient,
                kind=kind,
                origin=origin,
                subject=subject,
                title=title,
                body=body,
                created_at=now,
            )
            for recipient in unique_recipients
        )
        created = self._repository.add_many(drafts)
        return DeliveryOutcome(created=created, deduped=len(drafts) - created)

    def get_inbox(
        self,
        organization_id: OrganizationId,
        recipient_user_id: UserId,
        *,
        limit: int,
        offset: int,
        unread_only: bool = False,
    ) -> NotificationInboxPage:
        records = self._repository.list_for_recipient(
            organization_id,
            recipient_user_id,
            limit=limit,
            offset=offset,
            unread_only=unread_only,
        )
        return NotificationInboxPage(
            items=tuple(self._item(record) for record in records),
            unread_count=self._repository.count_unread(organization_id, recipient_user_id),
            limit=limit,
            offset=offset,
        )

    def mark_read(
        self,
        organization_id: OrganizationId,
        recipient_user_id: UserId,
        notification_id: UUID,
    ) -> NotificationItem:
        record = self._repository.mark_read(
            organization_id,
            recipient_user_id,
            notification_id,
        )
        if record is None:
            raise LookupError("Notification not found")
        return self._item(record)

    @staticmethod
    def _item(record: NotificationRecord) -> NotificationItem:
        kind = NotificationKind(record.kind)
        title, body = display_copy(kind, record.title, record.body)
        subject: NotificationSubject
        if record.review_case_id is not None:
            subject = ReviewCaseNotificationSubject(ReviewCaseId(record.review_case_id))
        elif record.finding_id is not None:
            subject = FindingNotificationSubject(FindingId(record.finding_id))
        elif record.action_item_id is not None:
            subject = ActionItemNotificationSubject(ActionItemId(record.action_item_id))
        else:
            raise RuntimeError("Persisted Notification has no typed subject")

        origin: NotificationOrigin
        if record.origin_activity_id is not None:
            origin = ActivityNotificationOrigin(ActivityId(record.origin_activity_id))
        elif record.automatic_origin_key is not None:
            origin = AutomaticReminderNotificationOrigin(record.automatic_origin_key)
        else:
            raise RuntimeError("Persisted Notification has no typed origin")

        return NotificationItem(
            id=NotificationId(record.id),
            organization_id=OrganizationId(record.organization_id),
            recipient_user_id=UserId(record.recipient_user_id),
            kind=kind,
            origin=origin,
            subject=subject,
            title=title,
            body=body,
            created_at=record.created_at,
            read_at=record.read_at,
        )
