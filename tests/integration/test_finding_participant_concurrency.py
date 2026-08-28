import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, select, update
from sqlalchemy.orm import Session

from easyaudit_next.composition import (
    build_notification_orchestrator,
    build_scenario_registry,
)
from easyaudit_next.notifications.persistence import NotificationRecord
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.persistence.models import OrganizationRecord, UserRecord
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyDepartmentRepository,
    SqlAlchemyUserRepository,
)
from easyaudit_next.review_core.application.review_findings import (
    ConcurrentFindingTransitionError,
    FindingLifecycleService,
)
from easyaudit_next.review_core.domain.models import Finding, FindingLifecycle, UserActor
from easyaudit_next.review_core.persistence.models import (
    ActivityRecord,
    CaseMemberRecord,
    FindingParticipantRecord,
    FindingRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)
from easyaudit_next.review_core.persistence.repositories import (
    SqlAlchemyReviewCoreRepository,
)

NOW = datetime(2026, 8, 28, 13, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


class _PausedParticipantGuardRepository(SqlAlchemyReviewCoreRepository):
    def __init__(self, session: Session, guard_ready: Event, release_guard: Event) -> None:
        super().__init__(session)
        self._guard_ready = guard_ready
        self._release_guard = release_guard

    def update_finding(
        self,
        finding: Finding,
        *,
        expected_lifecycle: FindingLifecycle,
    ) -> bool:
        # FindingParticipant uses a same-state CAS here as its final persisted
        # serialization barrier. Pause immediately before PostgreSQL acquires it.
        if finding.lifecycle is expected_lifecycle:
            self._guard_ready.set()
            if not self._release_guard.wait(timeout=10):
                raise TimeoutError("participant final guard was not released")
        return super().update_finding(
            finding,
            expected_lifecycle=expected_lifecycle,
        )


def _seed_terminal_race(
    engine: Engine,
    initial_lifecycle: FindingLifecycle,
) -> tuple[OrganizationId, UserId, UserId, object]:
    organization_id = OrganizationId(uuid4())
    lead_id = UserId(uuid4())
    candidate_id = UserId(uuid4())
    scenario_id = uuid4()
    scenario_version_id = uuid4()
    case_id = uuid4()
    finding_id = uuid4()

    with Session(engine) as session, session.begin():
        session.add(OrganizationRecord(id=organization_id, name=f"M3.5.3 {organization_id}"))
        session.add_all(
            [
                UserRecord(
                    id=lead_id,
                    organization_id=organization_id,
                    display_name="Participant Lead",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=candidate_id,
                    organization_id=organization_id,
                    display_name="Late Participant",
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
                title="Participant serialization case",
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
        session.add(
            FindingRecord(
                id=finding_id,
                organization_id=organization_id,
                case_id=case_id,
                title="Finding participant race",
                description=None,
                severity="high",
                lifecycle=initial_lifecycle.value,
                raised_by=lead_id,
                raised_at=NOW,
                scenario_data_json={
                    "issue_type": "control_gap",
                    "project_category": "assembly",
                },
            )
        )

    return organization_id, lead_id, candidate_id, finding_id


@pytest.mark.parametrize(
    ("initial_lifecycle", "terminal_lifecycle"),
    [
        (FindingLifecycle.VERIFYING, FindingLifecycle.CLOSED),
        (FindingLifecycle.OPEN, FindingLifecycle.VOIDED),
    ],
)
def test_participant_write_cannot_cross_committed_terminal_transition(
    postgres_engine: Engine,
    initial_lifecycle: FindingLifecycle,
    terminal_lifecycle: FindingLifecycle,
) -> None:
    organization_id, lead_id, candidate_id, finding_id = _seed_terminal_race(
        postgres_engine,
        initial_lifecycle,
    )
    guard_ready = Event()
    release_guard = Event()

    def add_participant() -> None:
        with Session(postgres_engine) as session, session.begin():
            users = SqlAlchemyUserRepository(session)
            lead = users.get(lead_id)
            assert lead is not None
            service = FindingLifecycleService(
                _PausedParticipantGuardRepository(session, guard_ready, release_guard),
                users,
                SqlAlchemyDepartmentRepository(session),
                build_scenario_registry(),
            )
            result = service.add_participant_result(
                lead,
                finding_id,
                UserActor(candidate_id),
                "owner",
                occurred_at=NOW,
            )
            build_notification_orchestrator(session).finding_participant_added(result)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(add_participant)
        assert guard_ready.wait(timeout=10)

        with Session(postgres_engine) as transition_session, transition_session.begin():
            changed = transition_session.execute(
                update(FindingRecord)
                .where(
                    FindingRecord.organization_id == organization_id,
                    FindingRecord.id == finding_id,
                    FindingRecord.lifecycle == initial_lifecycle.value,
                )
                .values(lifecycle=terminal_lifecycle.value)
            )
            assert changed.rowcount == 1

        release_guard.set()
        with pytest.raises(ConcurrentFindingTransitionError, match="Concurrent Finding transition"):
            future.result(timeout=10)

    with Session(postgres_engine) as verification:
        persisted_lifecycle = verification.scalar(
            select(FindingRecord.lifecycle).where(
                FindingRecord.organization_id == organization_id,
                FindingRecord.id == finding_id,
            )
        )
        participant_count = verification.scalar(
            select(func.count())
            .select_from(FindingParticipantRecord)
            .where(
                FindingParticipantRecord.organization_id == organization_id,
                FindingParticipantRecord.finding_id == finding_id,
                FindingParticipantRecord.user_id == candidate_id,
            )
        )
        activity_count = verification.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(
                ActivityRecord.organization_id == organization_id,
                ActivityRecord.finding_id == finding_id,
                ActivityRecord.event_type == "finding.participant_added",
            )
        )
        notification_count = verification.scalar(
            select(func.count())
            .select_from(NotificationRecord)
            .where(
                NotificationRecord.organization_id == organization_id,
                NotificationRecord.finding_id == finding_id,
            )
        )

        assert persisted_lifecycle == terminal_lifecycle.value
        assert participant_count == 0
        assert activity_count == 0
        assert notification_count == 0
