from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from easyaudit_next.composition import build_scenario_registry
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.application.review_findings import (
    ConcurrentFindingTransitionError,
)
from easyaudit_next.review_core.application.review_verification import VerificationClosureService
from easyaudit_next.review_core.persistence.models import ActivityRecord, SubmissionRecord
from easyaudit_next.review_core.persistence.verification_repositories import (
    SqlAlchemyVerificationClosureRepository,
)
from tests.integration.barrier_support import CountingBarrier
from tests.integration.test_review_verification_semantics import (
    NOW,
    _seed_case,
    postgres_engine,
)

__all__ = ["postgres_engine"]


class _SynchronizedCaseGuardRepository(SqlAlchemyVerificationClosureRepository):
    def __init__(self, session: Session, barrier: Barrier) -> None:
        super().__init__(session)
        self._barrier = barrier

    def lock_case_for_team_management(self, organization_id, case_id):
        self._barrier.wait(timeout=10)
        return super().lock_case_for_team_management(organization_id, case_id)


def test_two_verification_approvals_from_same_old_state_yield_one_conflict(
    postgres_engine: Engine,
) -> None:
    organization_id, _, finding_id, _, reviewer_id, _ = _seed_case(
        postgres_engine,
        finding_lifecycle="verifying",
    )
    barrier = CountingBarrier()

    def attempt_approve() -> str:
        with Session(postgres_engine, expire_on_commit=False) as session:
            reviewer = SqlAlchemyUserRepository(session).get(reviewer_id)
            assert reviewer is not None
            service = VerificationClosureService(
                _SynchronizedCaseGuardRepository(session, barrier),
                build_scenario_registry(),
            )
            try:
                service.submit_verification(
                    reviewer,
                    finding_id,
                    "approve",
                    {"result": "approved", "comment": "Concurrent verification"},
                    occurred_at=NOW,
                )
                session.commit()
                return "success"
            except ConcurrentFindingTransitionError:
                session.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(attempt_approve)
        second = executor.submit(attempt_approve)
        outcomes = sorted([first.result(), second.result()])

    assert barrier.hits == 2
    assert outcomes == ["conflict", "success"]
    with Session(postgres_engine) as verification:
        assert verification.scalar(
            select(func.count())
            .select_from(SubmissionRecord)
            .where(
                SubmissionRecord.organization_id == organization_id,
                SubmissionRecord.finding_id == finding_id,
                SubmissionRecord.purpose == "verification",
            )
        ) == 1
        assert verification.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(
                ActivityRecord.organization_id == organization_id,
                ActivityRecord.event_type == "finding.approved",
            )
        ) == 1
