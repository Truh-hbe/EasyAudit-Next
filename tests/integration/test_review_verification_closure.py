import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session

from easyaudit_next.composition import build_scenario_registry
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.persistence.models import OrganizationRecord, UserRecord
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.application.review_findings import (
    ConcurrentFindingTransitionError,
)
from easyaudit_next.review_core.application.review_planning import (
    ConcurrentCaseTransitionError,
)
from easyaudit_next.review_core.application.review_verification import (
    ClosureAwareReviewPlanningService,
    VerificationClosureService,
)
from easyaudit_next.review_core.domain.ids import FindingId, ReviewCaseId
from easyaudit_next.review_core.persistence.models import (
    ActivityRecord,
    CaseMemberRecord,
    FindingRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
    SubmissionRecord,
)
from easyaudit_next.review_core.persistence.repositories import (
    SqlAlchemyScenarioCatalogRepository,
)
from easyaudit_next.review_core.persistence.verification_repositories import (
    SqlAlchemyVerificationClosureRepository,
)
from tests.integration.barrier_support import CountingBarrier

NOW = datetime(2026, 8, 26, 15, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _seed_closure_case(
    engine: Engine,
    *,
    finding_lifecycle: str,
) -> tuple[OrganizationId, ReviewCaseId, FindingId, UserId, UserId]:
    organization_id = OrganizationId(uuid4())
    lead_id = UserId(uuid4())
    reviewer_id = UserId(uuid4())
    scenario_id = uuid4()
    scenario_version_id = uuid4()
    case_id = ReviewCaseId(uuid4())
    finding_id = FindingId(uuid4())

    with Session(engine) as session, session.begin():
        session.add(OrganizationRecord(id=organization_id, name=f"M2.5 {organization_id}"))
        session.flush()
        session.add_all(
            [
                UserRecord(
                    id=lead_id,
                    organization_id=organization_id,
                    display_name="Closure Lead",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=reviewer_id,
                    organization_id=organization_id,
                    display_name="Verification Reviewer",
                    platform_role="ordinary_user",
                ),
            ]
        )
        session.flush()
        session.add(
            ScenarioRecord(
                id=scenario_id,
                organization_id=organization_id,
                key="process_review",
                name="Process Review",
            )
        )
        session.flush()
        session.add(
            ScenarioVersionRecord(
                id=scenario_version_id,
                scenario_id=scenario_id,
                organization_id=organization_id,
                version=1,
                published_at=NOW,
            )
        )
        session.flush()
        session.add(
            ReviewCaseRecord(
                id=case_id,
                organization_id=organization_id,
                plan_id=None,
                scenario_version_id=scenario_version_id,
                title="M2.5 Closure Race",
                lifecycle="awaiting_closure",
                planned_start_at=None,
                planned_end_at=None,
                started_at=NOW,
                fieldwork_completed_at=NOW,
                closed_at=None,
                scenario_data_json={"area_code": "ASSY", "review_type": "routine"},
                created_by=lead_id,
                created_at=NOW,
            )
        )
        session.flush()
        session.add_all(
            [
                CaseMemberRecord(
                    organization_id=organization_id,
                    case_id=case_id,
                    user_id=lead_id,
                    role_key="lead",
                    joined_at=NOW,
                ),
                CaseMemberRecord(
                    organization_id=organization_id,
                    case_id=case_id,
                    user_id=reviewer_id,
                    role_key="reviewer",
                    joined_at=NOW,
                ),
            ]
        )
        session.flush()
        session.add(
            FindingRecord(
                id=finding_id,
                organization_id=organization_id,
                case_id=case_id,
                title="Closure aggregate race",
                description=None,
                severity="high",
                lifecycle=finding_lifecycle,
                raised_by=lead_id,
                raised_at=NOW,
                scenario_data_json={
                    "issue_type": "control_gap",
                    "project_category": "assembly",
                },
            )
        )

    return organization_id, case_id, finding_id, lead_id, reviewer_id


class _SynchronizedCaseGuardRepository(SqlAlchemyVerificationClosureRepository):
    def __init__(self, session: Session, barrier: Barrier) -> None:
        super().__init__(session)
        self._barrier = barrier

    def lock_case_for_team_management(self, organization_id, case_id):
        self._barrier.wait(timeout=10)
        return super().lock_case_for_team_management(organization_id, case_id)


def _planning_service(
    session: Session,
    repository: SqlAlchemyVerificationClosureRepository,
) -> ClosureAwareReviewPlanningService:
    return ClosureAwareReviewPlanningService(
        repository,
        SqlAlchemyScenarioCatalogRepository(session),
        SqlAlchemyUserRepository(session),
        build_scenario_registry(),
    )


def test_close_racing_final_approve_never_persists_closed_case_with_verifying_finding(
    postgres_engine: Engine,
) -> None:
    organization_id, case_id, finding_id, lead_id, reviewer_id = _seed_closure_case(
        postgres_engine,
        finding_lifecycle="verifying",
    )
    barrier = CountingBarrier()

    def attempt_close() -> str:
        with Session(postgres_engine, expire_on_commit=False) as session:
            lead = SqlAlchemyUserRepository(session).get(lead_id)
            assert lead is not None
            repository = _SynchronizedCaseGuardRepository(session, barrier)
            service = _planning_service(session, repository)
            try:
                service.transition_case(lead, case_id, "close", occurred_at=NOW)
                session.commit()
                return "close_success"
            except ValueError:
                session.rollback()
                return "close_invalid"
            except ConcurrentCaseTransitionError:
                session.rollback()
                return "close_conflict"

    def attempt_approve() -> str:
        with Session(postgres_engine, expire_on_commit=False) as session:
            reviewer = SqlAlchemyUserRepository(session).get(reviewer_id)
            assert reviewer is not None
            repository = _SynchronizedCaseGuardRepository(session, barrier)
            service = VerificationClosureService(repository, build_scenario_registry())
            try:
                service.submit_verification(
                    reviewer,
                    finding_id,
                    "approve",
                    {"result": "approved", "comment": "Verified"},
                    occurred_at=NOW,
                )
                session.commit()
                return "approve_success"
            except (ConcurrentCaseTransitionError, ConcurrentFindingTransitionError):
                session.rollback()
                return "approve_conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        close_future = executor.submit(attempt_close)
        approve_future = executor.submit(attempt_approve)
        outcomes = {close_future.result(), approve_future.result()}

    assert barrier.hits == 2
    assert outcomes in (
        {"close_success", "approve_success"},
        {"close_invalid", "approve_success"},
    )
    with Session(postgres_engine) as verification:
        case_lifecycle = verification.scalar(
            select(ReviewCaseRecord.lifecycle).where(
                ReviewCaseRecord.organization_id == organization_id,
                ReviewCaseRecord.id == case_id,
            )
        )
        finding_lifecycle = verification.scalar(
            select(FindingRecord.lifecycle).where(
                FindingRecord.organization_id == organization_id,
                FindingRecord.id == finding_id,
            )
        )
        verification_submissions = verification.scalar(
            select(func.count())
            .select_from(SubmissionRecord)
            .where(
                SubmissionRecord.organization_id == organization_id,
                SubmissionRecord.finding_id == finding_id,
                SubmissionRecord.purpose == "verification",
            )
        )
        assert (case_lifecycle, finding_lifecycle) != ("closed", "verifying")
        assert finding_lifecycle == "closed"
        assert verification_submissions == 1
        if case_lifecycle == "closed":
            assert finding_lifecycle == "closed"
        else:
            assert case_lifecycle == "awaiting_closure"


def test_close_racing_reopen_never_persists_closed_case_with_rectifying_finding(
    postgres_engine: Engine,
) -> None:
    organization_id, case_id, finding_id, lead_id, _ = _seed_closure_case(
        postgres_engine,
        finding_lifecycle="closed",
    )
    barrier = CountingBarrier()

    def attempt_close() -> str:
        with Session(postgres_engine, expire_on_commit=False) as session:
            lead = SqlAlchemyUserRepository(session).get(lead_id)
            assert lead is not None
            repository = _SynchronizedCaseGuardRepository(session, barrier)
            service = _planning_service(session, repository)
            try:
                service.transition_case(lead, case_id, "close", occurred_at=NOW)
                session.commit()
                return "close_success"
            except ValueError:
                session.rollback()
                return "close_invalid"
            except ConcurrentCaseTransitionError:
                session.rollback()
                return "close_conflict"

    def attempt_reopen() -> str:
        with Session(postgres_engine, expire_on_commit=False) as session:
            lead = SqlAlchemyUserRepository(session).get(lead_id)
            assert lead is not None
            repository = _SynchronizedCaseGuardRepository(session, barrier)
            service = VerificationClosureService(repository, build_scenario_registry())
            try:
                service.reopen_finding(
                    lead,
                    finding_id,
                    reason="Verification outcome no longer valid",
                    occurred_at=NOW,
                )
                session.commit()
                return "reopen_success"
            except (ConcurrentCaseTransitionError, ConcurrentFindingTransitionError):
                session.rollback()
                return "reopen_conflict"
            except ValueError:
                session.rollback()
                return "reopen_invalid"

    with ThreadPoolExecutor(max_workers=2) as executor:
        close_future = executor.submit(attempt_close)
        reopen_future = executor.submit(attempt_reopen)
        outcomes = {close_future.result(), reopen_future.result()}

    assert barrier.hits == 2
    assert outcomes in (
        {"close_success", "reopen_conflict"},
        {"close_invalid", "reopen_success"},
    )
    with Session(postgres_engine) as verification:
        case_lifecycle = verification.scalar(
            select(ReviewCaseRecord.lifecycle).where(
                ReviewCaseRecord.organization_id == organization_id,
                ReviewCaseRecord.id == case_id,
            )
        )
        finding_lifecycle = verification.scalar(
            select(FindingRecord.lifecycle).where(
                FindingRecord.organization_id == organization_id,
                FindingRecord.id == finding_id,
            )
        )
        reopen_activities = verification.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(
                ActivityRecord.organization_id == organization_id,
                ActivityRecord.finding_id == finding_id,
                ActivityRecord.event_type == "finding.reopened",
            )
        )
        assert (case_lifecycle, finding_lifecycle) != ("closed", "rectifying")
        if case_lifecycle == "closed":
            assert finding_lifecycle == "closed"
            assert reopen_activities == 0
        else:
            assert case_lifecycle == "awaiting_closure"
            assert finding_lifecycle == "rectifying"
            assert reopen_activities == 1
