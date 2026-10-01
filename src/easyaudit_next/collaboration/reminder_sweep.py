import re
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from easyaudit_next.collaboration.automatic_reminder import AutomaticReminderEvaluator
from easyaudit_next.platform.domain.ids import OrganizationId
from easyaudit_next.platform.persistence.models import OrganizationRecord
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
    created_deliveries: int = 0
    deduped_deliveries: int = 0
    failed_candidates: int = 0
    # (label, count) per failed candidate: exception class name plus SQLSTATE when there is one.
    failure_types: tuple[tuple[str, int], ...] = ()


_SQLSTATE = re.compile(r"^[0-9A-Z]{5}$")


def describe_failure(exc: BaseException) -> str:
    """Exception class name (plus SQLSTATE); never `str(exc)`, which can embed SQL and values."""
    label = type(exc).__name__
    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
    if isinstance(sqlstate, str) and _SQLSTATE.match(sqlstate):
        label = f"{label}/{sqlstate}"
    return label


class AutomaticReminderSweep:
    """Discover overdue targets once and delegate all semantics to the evaluator.

    This is an execution adapter, not a clock or cadence policy. The caller owns when
    it runs and supplies the stable occurrence identity shared by this sweep, and owns the
    transaction granularity:

    - `in_caller_transaction`: everything runs in the caller's session and transaction, and a
      failure propagates.
    - `per_candidate`: each discovery page and each candidate gets its own short transaction.
      A failing candidate rolls back alone and is counted; the sweep continues. Every
      transaction holds locks only for one candidate (Case/Action row, then its recipients'
      users), so it never accumulates locks across candidates (see docs/architecture.md).
    """

    def __init__(
        self,
        *,
        discovery: Callable[[], AbstractContextManager[Session]],
        candidate: Callable[[OrganizationId], AbstractContextManager[AutomaticReminderEvaluator]],
        isolate_failures: bool,
    ) -> None:
        self._discovery = discovery
        self._candidate = candidate
        self._isolate_failures = isolate_failures

    @classmethod
    def in_caller_transaction(
        cls, session: Session, evaluator: AutomaticReminderEvaluator
    ) -> "AutomaticReminderSweep":
        return cls(
            discovery=lambda: nullcontext(session),
            candidate=lambda _organization_id: nullcontext(evaluator),
            isolate_failures=False,
        )

    @classmethod
    def per_candidate(
        cls,
        transaction: Callable[[], AbstractContextManager[Session]],
        evaluator_factory: Callable[[Session], AutomaticReminderEvaluator],
    ) -> "AutomaticReminderSweep":
        """`transaction` must commit on success and roll back on exception, and be re-enterable."""

        def candidate(
            organization_id: OrganizationId,
        ) -> AbstractContextManager[AutomaticReminderEvaluator]:
            return _evaluator_in(transaction, evaluator_factory, organization_id)

        return cls(discovery=transaction, candidate=candidate, isolate_failures=True)

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

        tally = _Tally()
        for kind in ("case", "action"):
            cursor: UUID | None = None
            while True:
                with self._discovery() as session:
                    statement = (
                        self._case_candidates if kind == "case" else self._action_candidates
                    )(
                        as_of=as_of,
                        organization_id=organization_id,
                        after_id=cursor,
                        limit=batch_size,
                    )
                    rows = tuple(session.execute(statement))
                if not rows:
                    break
                for row in rows:
                    tally.candidates[kind] += 1
                    self._evaluate_candidate(
                        tally,
                        kind,
                        OrganizationId(row.organization_id),
                        row.id,
                        occurrence_key=occurrence_key,
                        as_of=as_of,
                    )
                cursor = rows[-1].id

        return ReminderSweepResult(
            case_candidates=tally.candidates["case"],
            action_candidates=tally.candidates["action"],
            eligible_cases=tally.eligible["case"],
            eligible_actions=tally.eligible["action"],
            recipient_deliveries_evaluated=tally.recipient_deliveries,
            created_deliveries=tally.created,
            deduped_deliveries=tally.deduped,
            failed_candidates=tally.failed,
            failure_types=tuple(sorted(tally.failure_types.items())),
        )

    def _evaluate_candidate(
        self,
        tally: "_Tally",
        kind: str,
        organization_id: OrganizationId,
        target_id: UUID,
        *,
        occurrence_key: str,
        as_of: datetime,
    ) -> None:
        try:
            with self._candidate(organization_id) as evaluator:
                evaluate = (
                    evaluator.evaluate_case_overdue
                    if kind == "case"
                    else evaluator.evaluate_action_overdue
                )
                result = evaluate(
                    organization_id, target_id, occurrence_key=occurrence_key, as_of=as_of
                )
        except Exception as exc:
            if not self._isolate_failures:
                raise
            tally.failed += 1
            tally.failure_types[describe_failure(exc)] += 1
            return
        if result.eligible:
            tally.eligible[kind] += 1
            tally.recipient_deliveries += result.recipient_count
            tally.created += result.created_count
            tally.deduped += result.deduped_count

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


@dataclass(slots=True)
class _Tally:
    candidates: Counter[str] = field(default_factory=Counter)
    eligible: Counter[str] = field(default_factory=Counter)
    recipient_deliveries: int = 0
    created: int = 0
    deduped: int = 0
    failed: int = 0
    failure_types: Counter[str] = field(default_factory=Counter)


def organization_key_share_lock(organization_id: OrganizationId) -> Select[tuple[UUID]]:
    # `read=True, key_share=True` is FOR KEY SHARE; `key_share=True` alone compiles to
    # FOR NO KEY UPDATE, which would make sweeps of one Organization exclude each other.
    return (
        select(OrganizationRecord.id)
        .where(OrganizationRecord.id == organization_id)
        .with_for_update(read=True, key_share=True)
    )


@contextmanager
def _evaluator_in(
    transaction: Callable[[], AbstractContextManager[Session]],
    evaluator_factory: Callable[[Session], AutomaticReminderEvaluator],
    organization_id: OrganizationId,
) -> Iterator[AutomaticReminderEvaluator]:
    with transaction() as session:
        # Inserting a Notification takes FOR KEY SHARE on its Organization row (FK) after the
        # Case/Action and User locks. Web operations lock Organization -> Case -> User, so take
        # the Organization first, in the same order, or the two form a cycle.
        session.execute(organization_key_share_lock(organization_id))
        yield evaluator_factory(session)
