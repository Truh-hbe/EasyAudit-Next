import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from easyaudit_next.composition import build_scenario_registry
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.persistence.models import OrganizationRecord, UserRecord
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.application.review_planning import (
    ConcurrentCaseTransitionError,
    ReviewAuthorizationError,
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

NOW = datetime(2026, 8, 26, 16, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _seed_case(
    engine: Engine,
    *,
    finding_lifecycle: str,
    include_unrelated: bool = False,
) -> tuple[OrganizationId, ReviewCaseId, FindingId, UserId, UserId, UserId | None]:
    organization_id = OrganizationId(uuid4())
    lead_id = UserId(uuid4())
    reviewer_id = UserId(uuid4())
    unrelated_id = UserId(uuid4()) if include_unrelated else None
    scenario_id = uuid4()
    scenario_version_id = uuid4()
    case_id = ReviewCaseId(uuid4())
    finding_id = FindingId(uuid4())

    with Session(engine) as session, session.begin():
        session.add(
            OrganizationRecord(
                id=organization_id,
                name=f"M2.5 semantics {organization_id}",
            )
        )
        session.flush()
        users = [
            UserRecord(
                id=lead_id,
                organization_id=organization_id,
                display_name="M2.5 Lead",
                platform_role="ordinary_user",
            ),
            UserRecord(
                id=reviewer_id,
                organization_id=organization_id,
                display_name="M2.5 Reviewer",
                platform_role="ordinary_user",
            ),
        ]
        if unrelated_id is not None:
            users.append(
                UserRecord(
                    id=unrelated_id,
                    organization_id=organization_id,
                    display_name="Unrelated User",
                    platform_role="ordinary_user",
                )
            )
        session.add_all(users)
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
                title="M2.5 Semantics",
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
                title="Verification semantics",
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

    return organization_id, case_id, finding_id, lead_id, reviewer_id, unrelated_id


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


def test_verification_reject_is_atomic_submission_and_activity(postgres_engine: Engine) -> None:
    organization_id, _, finding_id, _, reviewer_id, _ = _seed_case(
        postgres_engine,
        finding_lifecycle="verifying",
    )
    with Session(postgres_engine, expire_on_commit=False) as session:
        reviewer = SqlAlchemyUserRepository(session).get(reviewer_id)
        assert reviewer is not None
        service = VerificationClosureService(
            SqlAlchemyVerificationClosureRepository(session),
            build_scenario_registry(),
        )
        submission, finding = service.submit_verification(
            reviewer,
            finding_id,
            "reject",
            {"result": "rejected", "comment": "Evidence is incomplete"},
            occurred_at=NOW,
        )
        session.commit()

    assert finding.lifecycle.value == "rectifying"
    assert submission.purpose.value == "verification"
    with Session(postgres_engine) as verification:
        assert verification.scalar(
            select(FindingRecord.lifecycle).where(FindingRecord.id == finding_id)
        ) == "rectifying"
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
                ActivityRecord.submission_id == submission.id,
                ActivityRecord.event_type == "finding.rejected",
            )
        ) == 1


def test_case_close_uses_real_terminal_aggregate(postgres_engine: Engine) -> None:
    _, case_id, _, lead_id, _, _ = _seed_case(
        postgres_engine,
        finding_lifecycle="verifying",
    )
    with Session(postgres_engine, expire_on_commit=False) as session:
        lead = SqlAlchemyUserRepository(session).get(lead_id)
        assert lead is not None
        service = _planning_service(session, SqlAlchemyVerificationClosureRepository(session))
        with pytest.raises(ValueError, match="closed or voided"):
            service.transition_case(lead, case_id, "close", occurred_at=NOW)
        session.rollback()

    with Session(postgres_engine) as verification:
        assert verification.scalar(
            select(ReviewCaseRecord.lifecycle).where(ReviewCaseRecord.id == case_id)
        ) == "awaiting_closure"


def test_case_close_succeeds_when_all_findings_are_terminal(postgres_engine: Engine) -> None:
    organization_id, case_id, _, lead_id, _, _ = _seed_case(
        postgres_engine,
        finding_lifecycle="closed",
    )
    with Session(postgres_engine, expire_on_commit=False) as session:
        lead = SqlAlchemyUserRepository(session).get(lead_id)
        assert lead is not None
        service = _planning_service(session, SqlAlchemyVerificationClosureRepository(session))
        closed = service.transition_case(lead, case_id, "close", occurred_at=NOW)
        session.commit()

    assert closed.lifecycle.value == "closed"
    with Session(postgres_engine) as verification:
        assert verification.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(
                ActivityRecord.organization_id == organization_id,
                ActivityRecord.review_case_id == case_id,
                ActivityRecord.event_type == "review_case.transitioned",
            )
        ) == 1


class _FailAfterSubmissionRepository(SqlAlchemyVerificationClosureRepository):
    def add_submission(self, submission) -> None:
        super().add_submission(submission)
        self._session.flush()
        raise IntegrityError("forced verification persistence failure", {}, RuntimeError("forced"))


def test_verification_persistence_failure_rolls_back_finding_submission_and_activity(
    postgres_engine: Engine,
) -> None:
    organization_id, _, finding_id, _, reviewer_id, _ = _seed_case(
        postgres_engine,
        finding_lifecycle="verifying",
    )
    with Session(postgres_engine, expire_on_commit=False) as session:
        reviewer = SqlAlchemyUserRepository(session).get(reviewer_id)
        assert reviewer is not None
        service = VerificationClosureService(
            _FailAfterSubmissionRepository(session),
            build_scenario_registry(),
        )
        with pytest.raises(IntegrityError, match="forced verification persistence failure"):
            service.submit_verification(
                reviewer,
                finding_id,
                "approve",
                {"result": "approved", "comment": "Would have approved"},
                occurred_at=NOW,
            )
        session.rollback()

    with Session(postgres_engine) as verification:
        assert verification.scalar(
            select(FindingRecord.lifecycle).where(FindingRecord.id == finding_id)
        ) == "verifying"
        assert verification.scalar(
            select(func.count())
            .select_from(SubmissionRecord)
            .where(
                SubmissionRecord.organization_id == organization_id,
                SubmissionRecord.finding_id == finding_id,
                SubmissionRecord.purpose == "verification",
            )
        ) == 0
        assert verification.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(
                ActivityRecord.organization_id == organization_id,
                ActivityRecord.event_type == "finding.approved",
            )
        ) == 0


def test_unrelated_user_fails_authorization_before_verification_validation(
    postgres_engine: Engine,
) -> None:
    _, _, finding_id, _, _, unrelated_id = _seed_case(
        postgres_engine,
        finding_lifecycle="verifying",
        include_unrelated=True,
    )
    assert unrelated_id is not None
    with Session(postgres_engine, expire_on_commit=False) as session:
        unrelated = SqlAlchemyUserRepository(session).get(unrelated_id)
        assert unrelated is not None
        service = VerificationClosureService(
            SqlAlchemyVerificationClosureRepository(session),
            build_scenario_registry(),
        )
        with pytest.raises(ReviewAuthorizationError, match="not visible"):
            service.submit_verification(
                unrelated,
                finding_id,
                "not-a-real-verification-action",
                {},
                occurred_at=NOW,
            )
        session.rollback()


class _SynchronizedCaseGuardRepository(SqlAlchemyVerificationClosureRepository):
    def __init__(self, session: Session, barrier: Barrier) -> None:
        super().__init__(session)
        self._barrier = barrier

    def lock_case_for_closure(self, organization_id, case_id):
        self._barrier.wait(timeout=10)
        return super().lock_case_for_closure(organization_id, case_id)


def test_two_concurrent_case_close_callers_keep_case_cas_semantics(
    postgres_engine: Engine,
) -> None:
    organization_id, case_id, _, lead_id, _, _ = _seed_case(
        postgres_engine,
        finding_lifecycle="closed",
    )
    barrier = Barrier(2)

    def attempt_close() -> str:
        with Session(postgres_engine, expire_on_commit=False) as session:
            lead = SqlAlchemyUserRepository(session).get(lead_id)
            assert lead is not None
            repository = _SynchronizedCaseGuardRepository(session, barrier)
            service = _planning_service(session, repository)
            try:
                service.transition_case(lead, case_id, "close", occurred_at=NOW)
                session.commit()
                return "success"
            except ConcurrentCaseTransitionError:
                session.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(attempt_close)
        second = executor.submit(attempt_close)
        outcomes = sorted([first.result(), second.result()])

    assert outcomes == ["conflict", "success"]
    with Session(postgres_engine) as verification:
        assert verification.scalar(
            select(ReviewCaseRecord.lifecycle).where(ReviewCaseRecord.id == case_id)
        ) == "closed"
        assert verification.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(
                ActivityRecord.organization_id == organization_id,
                ActivityRecord.review_case_id == case_id,
                ActivityRecord.event_type == "review_case.transitioned",
            )
        ) == 1
