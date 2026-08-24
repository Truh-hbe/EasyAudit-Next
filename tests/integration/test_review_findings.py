import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from easyaudit_next.composition import build_scenario_registry
from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.persistence.models import (
    DepartmentRecord,
    OrganizationRecord,
    UserRecord,
)
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyDepartmentRepository,
    SqlAlchemyUserRepository,
)
from easyaudit_next.review_core.application.review_findings import (
    ConcurrentFindingTransitionError,
    FindingLifecycleService,
)
from easyaudit_next.review_core.application.review_planning import (
    ReviewAuthorizationError,
    ReviewPlanningService,
)
from easyaudit_next.review_core.domain.models import (
    Activity,
    DepartmentActor,
    Finding,
    FindingActivitySubject,
    FindingLifecycle,
    FindingSeverity,
    ScenarioKey,
    ScenarioVersion,
    UserActor,
)
from easyaudit_next.review_core.persistence.models import (
    ActivityRecord,
    FindingParticipantRecord,
    FindingRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)
from easyaudit_next.review_core.persistence.repositories import (
    SqlAlchemyReviewCoreRepository,
    SqlAlchemyScenarioCatalogRepository,
)

NOW = datetime(2026, 8, 24, 9, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _seed_process_review(
    engine: Engine,
) -> tuple[OrganizationId, DepartmentId, UserId, UserId, UserId]:
    organization_id = OrganizationId(uuid4())
    department_id = DepartmentId(uuid4())
    lead_id = UserId(uuid4())
    owner_id = UserId(uuid4())
    department_member_id = UserId(uuid4())
    scenario_id = uuid4()
    with Session(engine) as session, session.begin():
        session.add(
            OrganizationRecord(id=organization_id, name=f"M2.3 {organization_id}")
        )
        session.flush()
        session.add(
            DepartmentRecord(
                id=department_id,
                organization_id=organization_id,
                name="Operations",
            )
        )
        session.flush()
        session.add_all(
            [
                UserRecord(
                    id=lead_id,
                    organization_id=organization_id,
                    display_name="Finding Lead",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=owner_id,
                    organization_id=organization_id,
                    display_name="Finding Owner",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=department_member_id,
                    organization_id=organization_id,
                    primary_department_id=department_id,
                    display_name="Department Member",
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
                id=uuid4(),
                scenario_id=scenario_id,
                organization_id=organization_id,
                version=1,
                published_at=NOW,
            )
        )
    return (
        organization_id,
        department_id,
        lead_id,
        owner_id,
        department_member_id,
    )


def _planning_service(session: Session) -> ReviewPlanningService:
    return ReviewPlanningService(
        SqlAlchemyReviewCoreRepository(session),
        SqlAlchemyScenarioCatalogRepository(session),
        SqlAlchemyUserRepository(session),
        build_scenario_registry(),
    )


def _finding_service(
    session: Session,
    repository: SqlAlchemyReviewCoreRepository | None = None,
) -> FindingLifecycleService:
    return FindingLifecycleService(
        repository or SqlAlchemyReviewCoreRepository(session),
        SqlAlchemyUserRepository(session),
        SqlAlchemyDepartmentRepository(session),
        build_scenario_registry(),
    )


def _create_case_and_finding(
    session: Session,
    lead_id: UserId,
) -> tuple[FindingLifecycleService, Finding]:
    lead = SqlAlchemyUserRepository(session).get(lead_id)
    assert lead is not None
    review_case = _planning_service(session).create_case(
        lead,
        ScenarioKey("process_review"),
        ScenarioVersion(1),
        f"M2.3 Case {uuid4()}",
        {"area_code": "ASSY", "review_type": "routine"},
        occurred_at=NOW,
    )
    service = _finding_service(session)
    finding = service.create_finding(
        lead,
        review_case.id,
        "Calibration evidence is missing",
        FindingSeverity.HIGH,
        {"issue_type": "control_gap", "project_category": "assembly"},
        occurred_at=NOW,
    )
    return service, finding


def test_m2_3_migration_adds_finding_scenario_data(postgres_engine: Engine) -> None:
    names = {column["name"] for column in inspect(postgres_engine).get_columns("findings")}
    assert "scenario_data" in names


def test_finding_and_activity_persist_with_version_owned_data(
    postgres_engine: Engine,
) -> None:
    organization_id, _, lead_id, _, _ = _seed_process_review(postgres_engine)
    with Session(postgres_engine, expire_on_commit=False) as session:
        _, finding = _create_case_and_finding(session, lead_id)
        finding_id = finding.id
        session.commit()

    with Session(postgres_engine) as verification:
        record = verification.scalar(
            select(FindingRecord).where(
                FindingRecord.organization_id == organization_id,
                FindingRecord.id == finding_id,
            )
        )
        created_count = verification.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(
                ActivityRecord.organization_id == organization_id,
                ActivityRecord.finding_id == finding_id,
                ActivityRecord.event_type == "finding.created",
            )
        )
        assert record is not None
        assert record.lifecycle == "open"
        assert record.scenario_data_json == {
            "issue_type": "control_gap",
            "project_category": "assembly",
        }
        assert created_count == 1


class _RejectFindingCreatedActivityRepository(SqlAlchemyReviewCoreRepository):
    """Fail after the Finding flush through the real Activity CHECK constraint."""

    def add_activity(self, activity: Activity) -> None:
        if not isinstance(activity.subject, FindingActivitySubject):
            super().add_activity(activity)
            return
        self._session.add(
            ActivityRecord(
                id=uuid4(),
                organization_id=activity.organization_id,
                actor_id=activity.actor_id,
                event_type="",
                occurred_at=activity.occurred_at,
                finding_id=activity.subject.finding_id,
                metadata_json={},
            )
        )
        self._session.flush()


def test_finding_creation_rolls_back_when_created_activity_fails(
    postgres_engine: Engine,
) -> None:
    organization_id, _, lead_id, _, _ = _seed_process_review(postgres_engine)
    with Session(postgres_engine, expire_on_commit=False) as setup:
        lead = SqlAlchemyUserRepository(setup).get(lead_id)
        assert lead is not None
        review_case = _planning_service(setup).create_case(
            lead,
            ScenarioKey("process_review"),
            ScenarioVersion(1),
            f"M2.3 rollback Case {uuid4()}",
            {"area_code": "ASSY", "review_type": "routine"},
            occurred_at=NOW,
        )
        case_id = review_case.id
        setup.commit()

    title = f"M2.3 rollback Finding {uuid4()}"
    with pytest.raises(IntegrityError):
        with Session(postgres_engine) as session, session.begin():
            lead = SqlAlchemyUserRepository(session).get(lead_id)
            assert lead is not None
            service = _finding_service(
                session,
                _RejectFindingCreatedActivityRepository(session),
            )
            service.create_finding(
                lead,
                case_id,
                title,
                FindingSeverity.MEDIUM,
                {"issue_type": "control_gap", "project_category": "assembly"},
                occurred_at=NOW,
            )

    with Session(postgres_engine) as verification:
        finding_count = verification.scalar(
            select(func.count())
            .select_from(FindingRecord)
            .where(
                FindingRecord.organization_id == organization_id,
                FindingRecord.title == title,
            )
        )
        assert finding_count == 0


def test_direct_and_department_participants_are_scoped_and_drive_visibility(
    postgres_engine: Engine,
) -> None:
    (
        organization_id,
        department_id,
        lead_id,
        owner_id,
        department_member_id,
    ) = _seed_process_review(postgres_engine)
    with Session(postgres_engine, expire_on_commit=False) as session:
        users = SqlAlchemyUserRepository(session)
        lead = users.get(lead_id)
        owner = users.get(owner_id)
        department_member = users.get(department_member_id)
        assert lead is not None and owner is not None and department_member is not None
        service, finding = _create_case_and_finding(session, lead_id)
        service.add_participant(
            lead,
            finding.id,
            UserActor(owner.id),
            "owner",
            occurred_at=NOW,
        )
        service.add_participant(
            lead,
            finding.id,
            DepartmentActor(department_id),
            "responsible_department",
            occurred_at=NOW,
        )

        assert service.get_finding(owner, finding.id).id == finding.id
        assert service.get_finding(department_member, finding.id).id == finding.id
        assert _planning_service(session).get_case(owner, finding.case_id).id == finding.case_id
        assert (
            _planning_service(session).get_case(department_member, finding.case_id).id
            == finding.case_id
        )
        with pytest.raises(ReviewAuthorizationError):
            service.transition_finding(department_member, finding.id, "issue")
        session.commit()

    with Session(postgres_engine) as verification:
        participant_count = verification.scalar(
            select(func.count())
            .select_from(FindingParticipantRecord)
            .where(
                FindingParticipantRecord.organization_id == organization_id,
                FindingParticipantRecord.finding_id == finding.id,
            )
        )
        assert participant_count == 2

    foreign_organization_id, _, foreign_lead_id, _, _ = _seed_process_review(
        postgres_engine
    )
    with Session(postgres_engine) as session:
        users = SqlAlchemyUserRepository(session)
        local_lead = users.get(lead_id)
        foreign_lead = users.get(foreign_lead_id)
        assert local_lead is not None and foreign_lead is not None
        with pytest.raises(LookupError, match="organization User"):
            _finding_service(session).add_participant(
                local_lead,
                finding.id,
                UserActor(foreign_lead.id),
                "owner",
            )
        assert (
            SqlAlchemyReviewCoreRepository(session).get_finding(
                foreign_organization_id,
                finding.id,
            )
            is None
        )
        with pytest.raises(LookupError, match="Finding not found"):
            _finding_service(session).get_finding(foreign_lead, finding.id)


class _SynchronizedFindingRepository(SqlAlchemyReviewCoreRepository):
    def __init__(self, session: Session, barrier: Barrier) -> None:
        super().__init__(session)
        self._barrier = barrier

    def update_finding(
        self,
        finding: Finding,
        *,
        expected_lifecycle: FindingLifecycle,
    ) -> bool:
        self._barrier.wait(timeout=10)
        return super().update_finding(
            finding,
            expected_lifecycle=expected_lifecycle,
        )


def test_concurrent_finding_transition_allows_only_one_old_state_to_advance(
    postgres_engine: Engine,
) -> None:
    organization_id, _, lead_id, _, _ = _seed_process_review(postgres_engine)
    with Session(postgres_engine, expire_on_commit=False) as setup:
        _, finding = _create_case_and_finding(setup, lead_id)
        finding_id = finding.id
        setup.commit()

    barrier = Barrier(2)

    def attempt_issue() -> str:
        with Session(postgres_engine, expire_on_commit=False) as session:
            lead = SqlAlchemyUserRepository(session).get(lead_id)
            assert lead is not None
            repository = _SynchronizedFindingRepository(session, barrier)
            service = _finding_service(session, repository)
            try:
                service.transition_finding(lead, finding_id, "issue", occurred_at=NOW)
                session.commit()
            except ConcurrentFindingTransitionError:
                session.rollback()
                return "conflict"
            return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(attempt_issue) for _ in range(2)]
        outcomes = sorted(future.result() for future in futures)

    assert outcomes == ["conflict", "success"]
    with Session(postgres_engine) as verification:
        persisted = verification.scalar(
            select(FindingRecord).where(
                FindingRecord.organization_id == organization_id,
                FindingRecord.id == finding_id,
            )
        )
        transition_count = verification.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(
                ActivityRecord.organization_id == organization_id,
                ActivityRecord.finding_id == finding_id,
                ActivityRecord.event_type == "finding.transitioned",
            )
        )
        assert persisted is not None
        assert persisted.lifecycle == "rectifying"
        assert transition_count == 1
