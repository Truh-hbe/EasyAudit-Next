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
from easyaudit_next.review_core.application.review_closure_findings import (
    ClosureAwareFindingLifecycleService,
)
from easyaudit_next.review_core.application.review_planning import (
    ConcurrentCaseTransitionError,
)
from easyaudit_next.review_core.application.review_verification import (
    ClosureAwareReviewPlanningService,
)
from easyaudit_next.review_core.domain.ids import ReviewCaseId
from easyaudit_next.review_core.domain.models import FindingSeverity
from easyaudit_next.review_core.persistence.models import (
    CaseMemberRecord,
    FindingRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)
from easyaudit_next.review_core.persistence.repositories import (
    SqlAlchemyScenarioCatalogRepository,
)
from easyaudit_next.review_core.persistence.verification_repositories import (
    SqlAlchemyVerificationClosureRepository,
)
from tests.integration.barrier_support import CountingBarrier

NOW = datetime(2026, 8, 26, 15, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _seed_in_progress_case(
    engine: Engine,
) -> tuple[OrganizationId, ReviewCaseId, UserId]:
    organization_id = OrganizationId(uuid4())
    lead_id = UserId(uuid4())
    scenario_id = uuid4()
    scenario_version_id = uuid4()
    case_id = ReviewCaseId(uuid4())

    with Session(engine) as session, session.begin():
        session.add(OrganizationRecord(id=organization_id, name=f"M2.5 create {organization_id}"))
        session.flush()
        session.add(
            UserRecord(
                id=lead_id,
                organization_id=organization_id,
                display_name="Finding Creation Lead",
                platform_role="ordinary_user",
            )
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
                title="M2.5 Finding Create Cutover",
                lifecycle="in_progress",
                planned_start_at=None,
                planned_end_at=None,
                started_at=NOW,
                fieldwork_completed_at=None,
                closed_at=None,
                scenario_data_json={"area_code": "ASSY", "review_type": "routine"},
                created_by=lead_id,
                created_at=NOW,
            )
        )
        session.flush()
        session.add(
            CaseMemberRecord(
                organization_id=organization_id,
                case_id=case_id,
                user_id=lead_id,
                role_key="lead",
                joined_at=NOW,
            )
        )

    return organization_id, case_id, lead_id


class _SynchronizedCaseGuardRepository(SqlAlchemyVerificationClosureRepository):
    def __init__(self, session: Session, barrier: Barrier) -> None:
        super().__init__(session)
        self._barrier = barrier

    def lock_case_for_team_management(self, organization_id, case_id):
        self._barrier.wait(timeout=10)
        return super().lock_case_for_team_management(organization_id, case_id)


def test_finding_create_racing_fieldwork_finish_cannot_arrive_after_case_cutover(
    postgres_engine: Engine,
) -> None:
    organization_id, case_id, lead_id = _seed_in_progress_case(postgres_engine)
    barrier = CountingBarrier()

    def attempt_create() -> str:
        with Session(postgres_engine, expire_on_commit=False) as session:
            lead = SqlAlchemyUserRepository(session).get(lead_id)
            assert lead is not None
            repository = _SynchronizedCaseGuardRepository(session, barrier)
            service = ClosureAwareFindingLifecycleService(
                repository,
                SqlAlchemyUserRepository(session),
                departments=_UnusedDepartmentRepository(),
                registry=build_scenario_registry(),
            )
            try:
                service.create_finding(
                    lead,
                    case_id,
                    "Concurrent fieldwork Finding",
                    FindingSeverity.HIGH,
                    {"issue_type": "control_gap", "project_category": "assembly"},
                    occurred_at=NOW,
                )
                session.commit()
                return "create_success"
            except ConcurrentCaseTransitionError:
                session.rollback()
                return "create_conflict"

    def attempt_finish() -> str:
        with Session(postgres_engine, expire_on_commit=False) as session:
            lead = SqlAlchemyUserRepository(session).get(lead_id)
            assert lead is not None
            repository = _SynchronizedCaseGuardRepository(session, barrier)
            service = ClosureAwareReviewPlanningService(
                repository,
                SqlAlchemyScenarioCatalogRepository(session),
                SqlAlchemyUserRepository(session),
                build_scenario_registry(),
            )
            service.transition_case(lead, case_id, "finish_fieldwork", occurred_at=NOW)
            session.commit()
            return "finish_success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        create_future = executor.submit(attempt_create)
        finish_future = executor.submit(attempt_finish)
        outcomes = {create_future.result(), finish_future.result()}

    assert barrier.hits == 2
    assert outcomes in (
        {"create_success", "finish_success"},
        {"create_conflict", "finish_success"},
    )
    with Session(postgres_engine) as verification:
        lifecycle = verification.scalar(
            select(ReviewCaseRecord.lifecycle).where(
                ReviewCaseRecord.organization_id == organization_id,
                ReviewCaseRecord.id == case_id,
            )
        )
        finding_count = verification.scalar(
            select(func.count())
            .select_from(FindingRecord)
            .where(
                FindingRecord.organization_id == organization_id,
                FindingRecord.case_id == case_id,
            )
        )
        assert lifecycle == "awaiting_closure"
        assert finding_count in {0, 1}


class _UnusedDepartmentRepository:
    def get(self, department_id):
        return None
