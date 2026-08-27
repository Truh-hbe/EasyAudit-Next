from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from easyaudit_next.collaboration.recipient_resolution import (
    RecipientResolver,
    RecipientSnapshot,
)
from easyaudit_next.notifications.models import (
    ActionItemNotificationSubject,
    FindingNotificationSubject,
    NotificationKind,
)
from easyaudit_next.notifications.service import NotificationService
from easyaudit_next.platform.domain.models import User
from easyaudit_next.review_core.domain.ids import ActionItemId, ActivityId, FindingId
from easyaudit_next.review_core.domain.models import (
    ActionItemActivitySubject,
    Activity,
    FindingActivitySubject,
)
from easyaudit_next.review_core.domain.scenario_capabilities import CollaborationRecipientIntent
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry
from easyaudit_next.review_core.persistence.models import (
    ActionItemRecord,
    FindingRecord,
)
from easyaudit_next.review_core.persistence.repositories import SqlAlchemyReviewCoreRepository

MANAGE_CASE_MEMBERS_PERMISSION = "manage_case_members"
VIEW_CASE_PERMISSION = "view_case"
VIEW_FINDING_PERMISSION = "view_finding"


class NudgeValidationError(ValueError):
    """Raised when a visible, authorized nudge has no eligible recipient."""


@dataclass(frozen=True, slots=True)
class NudgeResult:
    activity_id: ActivityId
    recipient_count: int


class ManualNudgeService:
    """Human nudge orchestration over existing Review facts and Scenario responsibility."""

    def __init__(
        self,
        session: Session,
        registry: ScenarioRegistry,
        notifications: NotificationService,
    ) -> None:
        self._session = session
        self._notifications = notifications
        self._recipients = RecipientResolver(session, registry)
        self._review_repository = SqlAlchemyReviewCoreRepository(session)

    def nudge_finding(
        self,
        actor: User,
        finding_id: UUID,
        *,
        occurred_at: datetime | None = None,
    ) -> NudgeResult:
        finding = self._session.scalar(
            select(FindingRecord).where(
                FindingRecord.organization_id == actor.organization_id,
                FindingRecord.id == finding_id,
            )
        )
        if finding is None:
            raise LookupError("Finding not found")
        snapshot = self._recipients.load(actor.organization_id, finding.case_id)
        self._authorize_sender(actor, snapshot, finding.id)
        recipients = self._recipients.recipients(
            snapshot,
            CollaborationRecipientIntent.FINDING_RECTIFICATION,
            finding_id=finding.id,
            exclude_user_id=actor.id,
        )
        if not recipients:
            raise NudgeValidationError("No eligible nudge recipients")

        now = self._occurred_at(occurred_at)
        activity = Activity(
            id=ActivityId(uuid4()),
            organization_id=actor.organization_id,
            subject=FindingActivitySubject(FindingId(finding.id)),
            event_type="finding.nudged",
            actor_id=actor.id,
            occurred_at=now,
            metadata={"recipient_count": len(recipients)},
        )
        self._review_repository.add_activity(activity)
        self._notifications.deliver(
            organization_id=actor.organization_id,
            recipients=recipients,
            kind=NotificationKind.MANUAL_FINDING_NUDGE,
            origin_activity_id=activity.id,
            subject=FindingNotificationSubject(FindingId(finding.id)),
            title="Finding nudge",
            body="A Finding needs your attention.",
            created_at=now,
        )
        return NudgeResult(activity_id=activity.id, recipient_count=len(recipients))

    def nudge_action_item(
        self,
        actor: User,
        action_item_id: UUID,
        *,
        occurred_at: datetime | None = None,
    ) -> NudgeResult:
        action = self._session.scalar(
            select(ActionItemRecord).where(
                ActionItemRecord.organization_id == actor.organization_id,
                ActionItemRecord.id == action_item_id,
            )
        )
        if action is None:
            raise LookupError("ActionItem not found")
        finding = self._session.scalar(
            select(FindingRecord).where(
                FindingRecord.organization_id == actor.organization_id,
                FindingRecord.id == action.finding_id,
            )
        )
        if finding is None:
            raise LookupError("ActionItem not found")

        snapshot = self._recipients.load(actor.organization_id, finding.case_id)
        self._authorize_sender(actor, snapshot, finding.id)
        recipients = self._recipients.recipients(
            snapshot,
            CollaborationRecipientIntent.ACTION_EXECUTION,
            finding_id=finding.id,
            action_item_id=action.id,
            exclude_user_id=actor.id,
        )
        if not recipients:
            raise NudgeValidationError("No eligible nudge recipients")

        now = self._occurred_at(occurred_at)
        typed_action_id = ActionItemId(action.id)
        activity = Activity(
            id=ActivityId(uuid4()),
            organization_id=actor.organization_id,
            subject=ActionItemActivitySubject(typed_action_id),
            event_type="action_item.nudged",
            actor_id=actor.id,
            occurred_at=now,
            metadata={"recipient_count": len(recipients)},
        )
        self._review_repository.add_activity(activity)
        self._notifications.deliver(
            organization_id=actor.organization_id,
            recipients=recipients,
            kind=NotificationKind.MANUAL_ACTION_NUDGE,
            origin_activity_id=activity.id,
            subject=ActionItemNotificationSubject(typed_action_id),
            title="ActionItem nudge",
            body="An ActionItem needs your attention.",
            created_at=now,
        )
        return NudgeResult(activity_id=activity.id, recipient_count=len(recipients))

    @staticmethod
    def _authorize_sender(
        actor: User,
        snapshot: RecipientSnapshot,
        finding_id: UUID,
    ) -> None:
        if not actor.is_active or actor.id not in snapshot.direct_case_member_ids:
            raise LookupError("ReviewCase not found")
        case_context = snapshot.case_context(actor.id)
        if not snapshot.policy.authorization.allows(
            MANAGE_CASE_MEMBERS_PERMISSION,
            case_context,
        ):
            raise LookupError("ReviewCase not found")
        if not snapshot.policy.authorization.allows(VIEW_CASE_PERMISSION, case_context):
            raise LookupError("ReviewCase not found")
        finding_context = snapshot.finding_context(actor.id, finding_id)
        if not snapshot.policy.authorization.allows(VIEW_FINDING_PERMISSION, finding_context):
            raise LookupError("Finding not found")

    @staticmethod
    def _occurred_at(value: datetime | None) -> datetime:
        occurred_at = value or datetime.now(UTC)
        if occurred_at.utcoffset() is None:
            raise ValueError("Nudge occurred_at must include UTC offset")
        return occurred_at
