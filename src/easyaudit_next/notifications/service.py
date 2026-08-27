from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from easyaudit_next.notifications.models import (
    ActionItemNotificationSubject,
    FindingNotificationSubject,
    NotificationDraft,
    NotificationId,
    NotificationInboxPage,
    NotificationItem,
    NotificationKind,
    NotificationSubject,
    ReviewCaseNotificationSubject,
)
from easyaudit_next.notifications.persistence import (
    NotificationRecord,
    SqlAlchemyNotificationRepository,
)
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.review_core.domain.ids import ActionItemId, ActivityId, FindingId, ReviewCaseId


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
                origin_activity_id=origin_activity_id,
                subject=subject,
                title=title,
                body=body,
                created_at=now,
            )
            for recipient in unique_recipients
        )
        self._repository.add_many(drafts)

    def get_inbox(
        self,
        organization_id: OrganizationId,
        recipient_user_id: UserId,
        *,
        limit: int,
        offset: int,
    ) -> NotificationInboxPage:
        records = self._repository.list_for_recipient(
            organization_id,
            recipient_user_id,
            limit=limit,
            offset=offset,
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
        subject: NotificationSubject
        if record.review_case_id is not None:
            subject = ReviewCaseNotificationSubject(ReviewCaseId(record.review_case_id))
        elif record.finding_id is not None:
            subject = FindingNotificationSubject(FindingId(record.finding_id))
        elif record.action_item_id is not None:
            subject = ActionItemNotificationSubject(ActionItemId(record.action_item_id))
        else:
            raise RuntimeError("Persisted Notification has no typed subject")
        return NotificationItem(
            id=NotificationId(record.id),
            organization_id=OrganizationId(record.organization_id),
            recipient_user_id=UserId(record.recipient_user_id),
            kind=NotificationKind(record.kind),
            origin_activity_id=ActivityId(record.origin_activity_id),
            subject=subject,
            title=record.title,
            body=record.body,
            created_at=record.created_at,
            read_at=record.read_at,
        )
