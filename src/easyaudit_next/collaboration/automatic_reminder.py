from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from easyaudit_next.collaboration.recipient_resolution import RecipientResolver
from easyaudit_next.notifications.copy import COPY
from easyaudit_next.notifications.models import (
    ActionItemNotificationSubject,
    NotificationKind,
    ReviewCaseNotificationSubject,
)
from easyaudit_next.notifications.service import NotificationService
from easyaudit_next.platform.domain.ids import OrganizationId
from easyaudit_next.review_core.domain.ids import ActionItemId, ReviewCaseId
from easyaudit_next.review_core.domain.scenario_capabilities import CollaborationRecipientIntent
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry
from easyaudit_next.review_core.persistence.models import (
    ActionItemRecord,
    FindingRecord,
    ReviewCaseRecord,
)

_CASE_OVERDUE_LIFECYCLES = {"scheduled", "in_progress"}
_ACTION_OVERDUE_LIFECYCLES = {"todo", "in_progress"}


@dataclass(frozen=True, slots=True)
class AutomaticReminderEvaluation:
    eligible: bool
    recipient_count: int = 0
    created_count: int = 0
    deduped_count: int = 0
    automatic_origin_key: str | None = None


class AutomaticReminderEvaluator:
    """Evaluate one supplied overdue occurrence without owning cadence or scheduling."""

    def __init__(
        self,
        session: Session,
        registry: ScenarioRegistry,
        notifications: NotificationService,
    ) -> None:
        self._session = session
        self._recipients = RecipientResolver(session, registry)
        self._notifications = notifications

    def evaluate_case_overdue(
        self,
        organization_id: OrganizationId,
        review_case_id: UUID,
        *,
        occurrence_key: str,
        as_of: datetime,
    ) -> AutomaticReminderEvaluation:
        evaluated_at = self._validate_inputs(occurrence_key, as_of)
        review_case = self._load_case(organization_id, review_case_id)
        if not self._case_is_overdue(review_case, evaluated_at):
            return AutomaticReminderEvaluation(eligible=False)
        assert review_case is not None

        current = self._load_case(organization_id, review_case_id, guard=True)
        if not self._case_is_overdue(current, evaluated_at):
            return AutomaticReminderEvaluation(eligible=False)
        assert current is not None
        assert current.planned_end_at is not None

        # Team changes commit under the Case lock, so resolve recipients only after it.
        snapshot = self._recipients.load(organization_id, current.id)
        recipients = self._recipients.recipients(
            snapshot,
            CollaborationRecipientIntent.CASE_DEADLINE,
        )

        origin_key = self._origin_key(
            subject_kind="review_case",
            subject_id=current.id,
            deadline=current.planned_end_at,
            occurrence_key=occurrence_key,
        )
        outcome = self._notifications.deliver_automatic(
            organization_id=organization_id,
            recipients=recipients,
            kind=NotificationKind.AUTOMATIC_CASE_REMINDER,
            automatic_origin_key=origin_key,
            subject=ReviewCaseNotificationSubject(ReviewCaseId(current.id)),
            title=COPY[NotificationKind.AUTOMATIC_CASE_REMINDER].title,
            body=COPY[NotificationKind.AUTOMATIC_CASE_REMINDER].body,
            created_at=evaluated_at,
        )
        return AutomaticReminderEvaluation(
            eligible=True,
            recipient_count=len(recipients),
            created_count=outcome.created,
            deduped_count=outcome.deduped,
            automatic_origin_key=origin_key,
        )

    def evaluate_action_overdue(
        self,
        organization_id: OrganizationId,
        action_item_id: UUID,
        *,
        occurrence_key: str,
        as_of: datetime,
    ) -> AutomaticReminderEvaluation:
        evaluated_at = self._validate_inputs(occurrence_key, as_of)
        action = self._load_action(organization_id, action_item_id)
        if not self._action_is_overdue(action, evaluated_at):
            return AutomaticReminderEvaluation(eligible=False)
        assert action is not None

        finding = self._session.scalar(
            select(FindingRecord).where(
                FindingRecord.organization_id == organization_id,
                FindingRecord.id == action.finding_id,
            )
        )
        if finding is None:
            return AutomaticReminderEvaluation(eligible=False)
        # Case before Action (global lock order): responsibility changes commit under the Case.
        if self._load_case(organization_id, finding.case_id, guard=True) is None:
            return AutomaticReminderEvaluation(eligible=False)
        current = self._load_action(organization_id, action_item_id, guard=True)
        if not self._action_is_overdue(current, evaluated_at):
            return AutomaticReminderEvaluation(eligible=False)
        assert current is not None
        assert current.due_at is not None

        snapshot = self._recipients.load(organization_id, finding.case_id)
        recipients = self._recipients.recipients(
            snapshot,
            CollaborationRecipientIntent.ACTION_EXECUTION,
            finding_id=finding.id,
            action_item_id=current.id,
        )

        origin_key = self._origin_key(
            subject_kind="action_item",
            subject_id=current.id,
            deadline=current.due_at,
            occurrence_key=occurrence_key,
        )
        outcome = self._notifications.deliver_automatic(
            organization_id=organization_id,
            recipients=recipients,
            kind=NotificationKind.AUTOMATIC_ACTION_REMINDER,
            automatic_origin_key=origin_key,
            subject=ActionItemNotificationSubject(ActionItemId(current.id)),
            title=COPY[NotificationKind.AUTOMATIC_ACTION_REMINDER].title,
            body=COPY[NotificationKind.AUTOMATIC_ACTION_REMINDER].body,
            created_at=evaluated_at,
        )
        return AutomaticReminderEvaluation(
            eligible=True,
            recipient_count=len(recipients),
            created_count=outcome.created,
            deduped_count=outcome.deduped,
            automatic_origin_key=origin_key,
        )

    def _load_case(
        self,
        organization_id: OrganizationId,
        review_case_id: UUID,
        *,
        guard: bool = False,
    ) -> ReviewCaseRecord | None:
        statement = select(ReviewCaseRecord).where(
            ReviewCaseRecord.organization_id == organization_id,
            ReviewCaseRecord.id == review_case_id,
        )
        if guard:
            statement = statement.with_for_update(key_share=True).execution_options(
                populate_existing=True
            )
        return self._session.scalar(statement)

    def _load_action(
        self,
        organization_id: OrganizationId,
        action_item_id: UUID,
        *,
        guard: bool = False,
    ) -> ActionItemRecord | None:
        statement = select(ActionItemRecord).where(
            ActionItemRecord.organization_id == organization_id,
            ActionItemRecord.id == action_item_id,
        )
        if guard:
            statement = statement.with_for_update(key_share=True).execution_options(
                populate_existing=True
            )
        return self._session.scalar(statement)

    @staticmethod
    def _case_is_overdue(review_case: ReviewCaseRecord | None, as_of: datetime) -> bool:
        return (
            review_case is not None
            and review_case.planned_end_at is not None
            and review_case.planned_end_at < as_of
            and review_case.lifecycle in _CASE_OVERDUE_LIFECYCLES
        )

    @staticmethod
    def _action_is_overdue(action: ActionItemRecord | None, as_of: datetime) -> bool:
        return (
            action is not None
            and action.due_at is not None
            and action.due_at < as_of
            and action.lifecycle in _ACTION_OVERDUE_LIFECYCLES
        )

    @staticmethod
    def _validate_inputs(occurrence_key: str, as_of: datetime) -> datetime:
        if not occurrence_key.strip() or occurrence_key != occurrence_key.strip():
            raise ValueError("Automatic reminder occurrence key must not be blank or padded")
        if as_of.utcoffset() is None:
            raise ValueError("Automatic reminder as_of must include UTC offset")
        return as_of

    @staticmethod
    def _origin_key(
        *,
        subject_kind: str,
        subject_id: UUID,
        deadline: datetime,
        occurrence_key: str,
    ) -> str:
        deadline_identity = deadline.astimezone(UTC).isoformat(timespec="microseconds")
        canonical = "|".join(
            (
                "m3.4",
                "overdue",
                subject_kind,
                str(subject_id),
                deadline_identity,
                occurrence_key,
            )
        )
        digest = sha256(canonical.encode("utf-8")).hexdigest()
        return f"automatic-overdue-v1:{digest}"
