import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session

from easyaudit_next.api.dependencies import (
    CurrentIdentity,
    get_database_session,
    require_business_identity,
)
from easyaudit_next.composition import build_scenario_registry
from easyaudit_next.main import create_app
from easyaudit_next.platform.domain.ids import AuthSessionId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import AuthSession
from easyaudit_next.platform.persistence.models import OrganizationRecord, UserRecord
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyDepartmentRepository,
    SqlAlchemyUserRepository,
)
from easyaudit_next.review_core.application.review_closure_findings import (
    ClosureAwareFindingLifecycleService,
)
from easyaudit_next.review_core.application.review_planning import (
    ConcurrentCaseTransitionError,
)
from easyaudit_next.review_core.application.review_verification import (
    ClosureAwareReviewPlanningService,
)
from easyaudit_next.review_core.domain.ids import FindingId, ReviewCaseId
from easyaudit_next.review_core.persistence.models import (
    ActionItemRecord,
    ActivityRecord,
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

NOW = datetime(2026, 8, 29, 11, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _seed_observation_case(
    engine: Engine,
) -> tuple[OrganizationId, ReviewCaseId, FindingId, UserId, UserId]:
    organization_id = OrganizationId(uuid4())
    lead_id = UserId(uuid4())
    reviewer_id = UserId(uuid4())
    scenario_id = uuid4()
    scenario_version_id = uuid4()
    case_id = ReviewCaseId(uuid4())
    finding_id = FindingId(uuid4())

    with Session(engine) as session, session.begin():
        session.add(
            OrganizationRecord(
                id=organization_id,
                name=f"M4.1 compliance race {organization_id}",
            )
        )
        session.flush()
        session.add_all(
            [
                UserRecord(
                    id=lead_id,
                    organization_id=organization_id,
                    display_name="Compliance Lead",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=reviewer_id,
                    organization_id=organization_id,
                    display_name="Compliance Reviewer",
                    platform_role="ordinary_user",
                ),
            ]
        )
        session.flush()
        session.add(
            ScenarioRecord(
                id=scenario_id,
                organization_id=organization_id,
                key="compliance_review",
                name="Compliance Review",
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
                title="M4.1 Compliance Closure Race",
                lifecycle="awaiting_closure",
                planned_start_at=None,
                planned_end_at=None,
                started_at=NOW,
                fieldwork_completed_at=NOW,
                closed_at=None,
                scenario_data_json={
                    "standard_reference": "ISO 9001:2015",
                    "scope_summary": "Assembly control",
                },
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
                title="Document retention interval should be clarified",
                description=None,
                severity="low",
                lifecycle="open",
                raised_by=lead_id,
                raised_at=NOW,
                scenario_data_json={
                    "criterion_reference": "7.5.3",
                    "finding_type": "observation",
                },
            )
        )

    return organization_id, case_id, finding_id, lead_id, reviewer_id


class _CloseBarrierRepository(SqlAlchemyVerificationClosureRepository):
    def __init__(self, session: Session, barrier: Barrier) -> None:
        super().__init__(session)
        self._barrier = barrier

    def lock_case_for_team_management(self, organization_id, case_id):
        self._barrier.wait(timeout=10)
        return super().lock_case_for_team_management(organization_id, case_id)


class _AcceptBarrierRepository(SqlAlchemyVerificationClosureRepository):
    def __init__(self, session: Session, barrier: Barrier) -> None:
        super().__init__(session)
        self._barrier = barrier

    def lock_case_for_team_management(self, organization_id, case_id):
        self._barrier.wait(timeout=10)
        return super().lock_case_for_team_management(organization_id, case_id)


def test_case_close_racing_accept_observation_preserves_committed_terminality(
    postgres_engine: Engine,
) -> None:
    organization_id, case_id, finding_id, lead_id, reviewer_id = (
        _seed_observation_case(postgres_engine)
    )
    barrier = CountingBarrier()

    def attempt_close() -> str:
        with Session(postgres_engine, expire_on_commit=False) as session:
            lead = SqlAlchemyUserRepository(session).get(lead_id)
            assert lead is not None
            repository = _CloseBarrierRepository(session, barrier)
            service = ClosureAwareReviewPlanningService(
                repository,
                SqlAlchemyScenarioCatalogRepository(session),
                SqlAlchemyUserRepository(session),
                build_scenario_registry(),
            )
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

    def attempt_accept_observation() -> str:
        with Session(postgres_engine, expire_on_commit=False) as session:
            reviewer = SqlAlchemyUserRepository(session).get(reviewer_id)
            assert reviewer is not None
            repository = _AcceptBarrierRepository(session, barrier)
            service = ClosureAwareFindingLifecycleService(
                repository,
                SqlAlchemyUserRepository(session),
                SqlAlchemyDepartmentRepository(session),
                build_scenario_registry(),
            )
            service.transition_finding(
                reviewer,
                finding_id,
                "accept_observation",
                occurred_at=NOW,
            )
            session.commit()
            return "accept_success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        close_future = executor.submit(attempt_close)
        accept_future = executor.submit(attempt_accept_observation)
        outcomes = {close_future.result(), accept_future.result()}

    assert barrier.hits == 2
    assert outcomes in (
        {"close_success", "accept_success"},
        {"close_invalid", "accept_success"},
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
        transition_activities = verification.scalars(
            select(ActivityRecord).where(
                ActivityRecord.organization_id == organization_id,
                ActivityRecord.finding_id == finding_id,
                ActivityRecord.event_type == "finding.transitioned",
            )
        ).all()

        assert finding_lifecycle == "closed"
        assert not (
            case_lifecycle == "closed"
            and finding_lifecycle not in {"closed", "voided"}
        )
        assert case_lifecycle in {"awaiting_closure", "closed"}
        assert len(transition_activities) == 1
        assert transition_activities[0].metadata_json == {
            "action": "accept_observation",
            "from_lifecycle": "open",
            "to_lifecycle": "closed",
        }


def test_generic_http_transition_endpoint_accepts_compliance_observation(
    postgres_engine: Engine,
) -> None:
    organization_id, _, finding_id, _, reviewer_id = _seed_observation_case(
        postgres_engine
    )
    with Session(postgres_engine) as session:
        reviewer = SqlAlchemyUserRepository(session).get(reviewer_id)
        assert reviewer is not None

    identity = CurrentIdentity(
        auth_session=AuthSession(
            id=AuthSessionId(uuid4()),
            organization_id=organization_id,
            user_id=reviewer_id,
            token_hash="0" * 64,
            expires_at=NOW + timedelta(hours=1),
            created_at=NOW,
        ),
        user=reviewer,
    )
    app = create_app()

    def database_session() -> Iterator[Session]:
        with Session(postgres_engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def business_identity() -> CurrentIdentity:
        return identity

    app.dependency_overrides[get_database_session] = database_session
    app.dependency_overrides[require_business_identity] = business_identity

    with TestClient(app, base_url="https://testserver") as client:
        response = client.post(
            f"/api/v1/findings/{finding_id}/transitions",
            json={"action": "accept_observation"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(finding_id)
    assert body["lifecycle"] == "closed"
    assert body["scenario_data"]["finding_type"] == "observation"

    with Session(postgres_engine) as verification:
        finding_lifecycle = verification.scalar(
            select(FindingRecord.lifecycle).where(FindingRecord.id == finding_id)
        )
        transition_activity = verification.scalar(
            select(ActivityRecord).where(
                ActivityRecord.organization_id == organization_id,
                ActivityRecord.finding_id == finding_id,
                ActivityRecord.event_type == "finding.transitioned",
            )
        )
        assert finding_lifecycle == "closed"
        assert transition_activity is not None
        assert transition_activity.metadata_json["action"] == "accept_observation"


def test_reopened_observation_returns_to_open_and_can_be_accepted_again(
    postgres_engine: Engine,
) -> None:
    organization_id, _, finding_id, _, reviewer_id = _seed_observation_case(
        postgres_engine
    )
    with Session(postgres_engine) as session:
        reviewer = SqlAlchemyUserRepository(session).get(reviewer_id)
        assert reviewer is not None

    identity = CurrentIdentity(
        auth_session=AuthSession(
            id=AuthSessionId(uuid4()),
            organization_id=organization_id,
            user_id=reviewer_id,
            token_hash="0" * 64,
            expires_at=NOW + timedelta(hours=1),
            created_at=NOW,
        ),
        user=reviewer,
    )
    app = create_app()

    def database_session() -> Iterator[Session]:
        with Session(postgres_engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    app.dependency_overrides[get_database_session] = database_session
    app.dependency_overrides[require_business_identity] = lambda: identity

    with TestClient(app, base_url="https://testserver") as client:
        accept = client.post(
            f"/api/v1/findings/{finding_id}/transitions",
            json={"action": "accept_observation"},
        )
        assert accept.status_code == 200
        assert accept.json()["lifecycle"] == "closed"

        reopen = client.post(
            f"/api/v1/findings/{finding_id}/reopen",
            json={"reason": "New evidence contradicts the acceptance"},
        )
        assert reopen.status_code == 200
        assert reopen.json()["lifecycle"] == "open"

        accept_again = client.post(
            f"/api/v1/findings/{finding_id}/transitions",
            json={"action": "accept_observation"},
        )
        assert accept_again.status_code == 200
        assert accept_again.json()["lifecycle"] == "closed"

    with Session(postgres_engine) as verification:
        assert verification.scalar(
            select(FindingRecord.lifecycle).where(FindingRecord.id == finding_id)
        ) == "closed"
        assert verification.scalar(
            select(func.count())
            .select_from(ActionItemRecord)
            .where(ActionItemRecord.finding_id == finding_id)
        ) == 0
        reopened = verification.scalar(
            select(ActivityRecord).where(
                ActivityRecord.finding_id == finding_id,
                ActivityRecord.event_type == "finding.reopened",
            )
        )
        assert reopened is not None
        assert reopened.metadata_json["from_lifecycle"] == "closed"
        assert reopened.metadata_json["to_lifecycle"] == "open"
