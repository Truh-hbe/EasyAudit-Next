from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from easyaudit_next.collaboration.automatic_reminder import AutomaticReminderEvaluator
from easyaudit_next.platform.domain.ids import OrganizationId
from easyaudit_next.review_core.persistence.models import ActionItemRecord, ReviewCaseRecord

_CASE_OVERDUE_LIFECYCLES = ("scheduled", "in_progress")
_ACTION_OVERDUE_LIFECYCLES = ("todo", "in_progress")


@dataclass(frozen=True, slots=True)
class ReminderSweepResult:
    case_candidates: int
    action_candidates: int
    eligible_cases: int
    eligible_actions: int
    recipient_deliveries_evaluated: int


class AutomaticReminderSweep:
    """Discover overdue targets once and delegate all semantics to the evaluator.

    This is an execution adapter, not a clock or cadence policy. The caller owns when
    it runs and supplies the stable occurrence identity shared by this sweep.
    """

    def __init__(self, session: Session, evaluator: AutomaticReminderEvaluator) -> None:
        self._session = session
        self._evaluator = evaluator

    def run_once(
        self,
        *,
        occurrence_key: str,
        as_of: datetime,
        organization_id: OrganizationId | None = None,
        batch_size: int = 250,
    ) -> ReminderSweepResult:
        if batch_size < 1 or batch_size > 1000:
            raise ValueError("Automatic reminder sweep batch_size must be between 1 and 1000")
        if as_of.utcoffset() is None:
            raise ValueError("Automatic reminder sweep as_of must include UTC offset")
        if not occurrence_key.strip() or occurrence_key != occurrence_key.strip():
            raise ValueError("Automatic reminder occurrence key must not be blank or padded")

        case_candidates = 0
        action_candidates = 0
        eligible_cases = 0
        eligible_actions = 0
        recipient_deliveries = 0

        cursor: UUID | None = None
        while True:
            rows = tuple(
                self._session.execute(
                    self._case_candidates(
                        as_of=as_of,
                        organization_id=organization_id,
                        after_id=cursor,
                        limit=batch_size,
                    )
                )
            )
            if not rows:
                break
            for row in rows:
                case_candidates += 1
                result = self._evaluator.evaluate_case_overdue(
                    OrganizationId(row.organization_id),
                    row.id,
                    occurrence_key=occurrence_key,
                    as_of=as_of,
                )
                if result.eligible:
                    eligible_cases += 1
                    recipient_deliveries += result.recipient_count
            cursor = rows[-1].id

        cursor = None
        while True:
            rows = tuple(
                self._session.execute(
                    self._action_candidates(
                        as_of=as_of,
                        organization_id=organization_id,
                        after_id=cursor,
                        limit=batch_size,
                    )
                )
            )
            if not rows:
                break
            for row in rows:
                action_candidates += 1
                result = self._evaluator.evaluate_action_overdue(
                    OrganizationId(row.organization_id),
                    row.id,
                    occurrence_key=occurrence_key,
                    as_of=as_of,
                )
                if result.eligible:
                    eligible_actions += 1
                    recipient_deliveries += result.recipient_count
            cursor = rows[-1].id

        return ReminderSweepResult(
            case_candidates=case_candidates,
            action_candidates=action_candidates,
            eligible_cases=eligible_cases,
            eligible_actions=eligible_actions,
            recipient_deliveries_evaluated=recipient_deliveries,
        )

    @staticmethod
    def _case_candidates(
        *,
        as_of: datetime,
        organization_id: OrganizationId | None,
        after_id: UUID | None,
        limit: int,
    ) -> Select[tuple[UUID, UUID]]:
        statement = select(
            ReviewCaseRecord.organization_id.label("organization_id"),
            ReviewCaseRecord.id.label("id"),
        ).where(
            ReviewCaseRecord.planned_end_at.is_not(None),
            ReviewCaseRecord.planned_end_at < as_of,
            ReviewCaseRecord.lifecycle.in_(_CASE_OVERDUE_LIFECYCLES),
        )
        if organization_id is not None:
            statement = statement.where(ReviewCaseRecord.organization_id == organization_id)
        if after_id is not None:
            statement = statement.where(ReviewCaseRecord.id > after_id)
        return statement.order_by(ReviewCaseRecord.id).limit(limit)

    @staticmethod
    def _action_candidates(
        *,
        as_of: datetime,
        organization_id: OrganizationId | None,
        after_id: UUID | None,
        limit: int,
    ) -> Select[tuple[UUID, UUID]]:
        statement = select(
            ActionItemRecord.organization_id.label("organization_id"),
            ActionItemRecord.id.label("id"),
        ).where(
            ActionItemRecord.due_at.is_not(None),
            ActionItemRecord.due_at < as_of,
            ActionItemRecord.lifecycle.in_(_ACTION_OVERDUE_LIFECYCLES),
        )
        if organization_id is not None:
            statement = statement.where(ActionItemRecord.organization_id == organization_id)
        if after_id is not None:
            statement = statement.where(ActionItemRecord.id > after_id)
        return statement.order_by(ActionItemRecord.id).limit(limit)
