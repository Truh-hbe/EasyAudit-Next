from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from easyaudit_next.infrastructure.database import Base
from easyaudit_next.notifications.models import (
    ActionItemNotificationSubject,
    FindingNotificationSubject,
    NotificationDraft,
    NotificationSubject,
    ReviewCaseNotificationSubject,
)
from easyaudit_next.platform.domain.ids import OrganizationId, UserId


class NotificationRecord(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_notifications_id_organization"),
        ForeignKeyConstraint(
            ["recipient_user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_notifications_recipient_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["review_case_id", "organization_id"],
            ["review_cases.id", "review_cases.organization_id"],
            name="fk_notifications_case_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["finding_id", "organization_id"],
            ["findings.id", "findings.organization_id"],
            name="fk_notifications_finding_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["action_item_id", "organization_id"],
            ["action_items.id", "action_items.organization_id"],
            name="fk_notifications_action_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "num_nonnulls(review_case_id, finding_id, action_item_id) = 1",
            name="ck_notifications_exactly_one_subject",
        ),
        CheckConstraint("kind = btrim(kind) AND kind <> ''", name="ck_notifications_kind"),
        CheckConstraint("title = btrim(title) AND title <> ''", name="ck_notifications_title"),
        UniqueConstraint(
            "organization_id",
            "recipient_user_id",
            "origin_activity_id",
            "kind",
            name="uq_notifications_delivery",
        ),
        Index(
            "ix_notifications_inbox",
            "organization_id",
            "recipient_user_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_notifications_unread",
            "organization_id",
            "recipient_user_id",
            "created_at",
            postgresql_where=text("read_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", name="fk_notifications_organization", ondelete="RESTRICT"),
    )
    recipient_user_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(100))
    origin_activity_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("activities.id", name="fk_notifications_origin_activity", ondelete="RESTRICT"),
    )
    review_case_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    finding_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    action_item_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SqlAlchemyNotificationRepository:
    """Notification persistence with PostgreSQL-enforced idempotency."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_many(self, drafts: tuple[NotificationDraft, ...]) -> None:
        if not drafts:
            return
        values: list[dict[str, object]] = []
        for draft in drafts:
            subject_columns = self._subject_columns(draft.subject)
            values.append(
                {
                    "id": draft.id,
                    "organization_id": draft.organization_id,
                    "recipient_user_id": draft.recipient_user_id,
                    "kind": draft.kind.value,
                    "origin_activity_id": draft.origin_activity_id,
                    "title": draft.title,
                    "body": draft.body,
                    "created_at": draft.created_at,
                    **subject_columns,
                }
            )
        statement = postgresql_insert(NotificationRecord).values(values)
        statement = statement.on_conflict_do_nothing(constraint="uq_notifications_delivery")
        self._session.execute(statement)

    def list_for_recipient(
        self,
        organization_id: OrganizationId,
        recipient_user_id: UserId,
        *,
        limit: int,
        offset: int,
    ) -> tuple[NotificationRecord, ...]:
        return tuple(
            self._session.scalars(
                select(NotificationRecord)
                .where(
                    NotificationRecord.organization_id == organization_id,
                    NotificationRecord.recipient_user_id == recipient_user_id,
                )
                .order_by(NotificationRecord.created_at.desc(), NotificationRecord.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )

    def count_unread(
        self,
        organization_id: OrganizationId,
        recipient_user_id: UserId,
    ) -> int:
        count = self._session.scalar(
            select(func.count(NotificationRecord.id)).where(
                NotificationRecord.organization_id == organization_id,
                NotificationRecord.recipient_user_id == recipient_user_id,
                NotificationRecord.read_at.is_(None),
            )
        )
        return int(count or 0)

    def mark_read(
        self,
        organization_id: OrganizationId,
        recipient_user_id: UserId,
        notification_id: UUID,
    ) -> NotificationRecord | None:
        statement = (
            update(NotificationRecord)
            .where(
                NotificationRecord.organization_id == organization_id,
                NotificationRecord.recipient_user_id == recipient_user_id,
                NotificationRecord.id == notification_id,
            )
            .values(read_at=func.coalesce(NotificationRecord.read_at, func.now()))
            .returning(NotificationRecord)
        )
        return self._session.scalars(statement).one_or_none()

    @staticmethod
    def _subject_columns(subject: NotificationSubject) -> dict[str, UUID | None]:
        columns: dict[str, UUID | None] = {
            "review_case_id": None,
            "finding_id": None,
            "action_item_id": None,
        }
        if isinstance(subject, ReviewCaseNotificationSubject):
            columns["review_case_id"] = subject.review_case_id
        elif isinstance(subject, FindingNotificationSubject):
            columns["finding_id"] = subject.finding_id
        elif isinstance(subject, ActionItemNotificationSubject):
            columns["action_item_id"] = subject.action_item_id
        else:
            raise TypeError("Unsupported Notification subject")
        return columns
