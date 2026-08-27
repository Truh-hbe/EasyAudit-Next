import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session

from easyaudit_next.api.dependencies import (
    CurrentIdentity,
    get_current_identity,
    get_database_session,
)
from easyaudit_next.main import create_app
from easyaudit_next.notifications.persistence import NotificationRecord
from easyaudit_next.platform.domain.ids import AuthSessionId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import AuthSession, PlatformRole, User
from easyaudit_next.platform.persistence.models import OrganizationRecord, UserRecord
from easyaudit_next.review_core.persistence.models import (
    ActivityRecord,
    CaseMemberRecord,
    FindingRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)

NOW = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _identity(
    organization_id: OrganizationId,
    user_id: UserId,
    *,
    platform_role: PlatformRole = PlatformRole.ORDINARY_USER,
) -> CurrentIdentity:
    user = User(
        id=user_id,
        organization_id=organization_id,
        display_name="Management API Caller",
        platform_role=platform_role,
    )
    return CurrentIdentity(
        auth_session=AuthSession(
            id=AuthSessionId(uuid4()),
            organization_id=organization_id,
            user_id=user_id,
            token_hash="a" * 64,
            expires_at=NOW + timedelta(hours=1),
            created_at=NOW,
        ),
        user=user,
    )


def _seed_process_review_api_shape(
    engine: Engine,
) -> tuple[OrganizationId, UserId, UserId, UUID, UUID, UUID]:
    organization_id = OrganizationId(uuid4())
    caller_id = UserId(uuid4())
    admin_id = UserId(uuid4())
    scenario_id = uuid4()
    version_id = uuid4()
    lead_case_id = uuid4()
    observer_case_id = uuid4()
    finding_id = uuid4()

    with Session(engine) as session, session.begin():
        session.add(OrganizationRecord(id=organization_id, name=f"Management API {organization_id}"))
        session.flush()
        session.add_all(
            [
                UserRecord(
                    id=caller_id,
                    organization_id=organization_id,
                    display_name="Management API Caller",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=admin_id,
                    organization_id=organization_id,
                    display_name="Platform Admin",
                    platform_role="system_admin",
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
                id=version_id,
                scenario_id=scenario_id,
                organization_id=organization_id,
                version=1,
                published_at=NOW,
            )
        )
        session.flush()
        session.add_all(
            [
                ReviewCaseRecord(
                    id=lead_case_id,
                    organization_id=organization_id,
                    plan_id=None,
                    scenario_version_id=version_id,
                    title="Managed lead Case",
                    lifecycle="in_progress",
                    planned_start_at=NOW - timedelta(days=2),
                    planned_end_at=NOW - timedelta(days=1),
                    started_at=NOW - timedelta(days=2),
                    fieldwork_completed_at=None,
                    closed_at=None,
                    scenario_data_json={},
                    created_by=caller_id,
                    created_at=NOW - timedelta(days=3),
                ),
                ReviewCaseRecord(
                    id=observer_case_id,
                    organization_id=organization_id,
                    plan_id=None,
                    scenario_version_id=version_id,
                    title="Observer-only Case",
                    lifecycle="in_progress",
                    planned_start_at=NOW - timedelta(days=1),
                    planned_end_at=NOW + timedelta(days=2),
                    started_at=NOW - timedelta(days=1),
                    fieldwork_completed_at=None,
                    closed_at=None,
                    scenario_data_json={},
                    created_by=caller_id,
                    created_at=NOW - timedelta(days=2),
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                CaseMemberRecord(
                    organization_id=organization_id,
                    case_id=lead_case_id,
                    user_id=caller_id,
                    role_key="lead",
                    joined_at=NOW,
                ),
                CaseMemberRecord(
                    organization_id=organization_id,
                    case_id=observer_case_id,
                    user_id=caller_id,
                    role_key="observer",
                    joined_at=NOW,
                ),
            ]
        )
        session.add(
            FindingRecord(
                id=finding_id,
                organization_id=organization_id,
                case_id=lead_case_id,
                title="Visible through lead Case role",
                description=None,
                severity="high",
                lifecycle="rectifying",
                raised_by=caller_id,
                raised_at=NOW - timedelta(hours=3),
                scenario_data_json={},
            )
        )

    return organization_id, caller_id, admin_id, lead_case_id, observer_case_id, finding_id


def _client_for_identity(engine: Engine, identity: CurrentIdentity) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_identity] = lambda: identity

    def database_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_database_session] = database_session
    return TestClient(app)


def _side_effect_counts(engine: Engine, organization_id: OrganizationId) -> tuple[int, int]:
    with Session(engine) as session:
        activity_count = session.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(ActivityRecord.organization_id == organization_id)
        )
        notification_count = session.scalar(
            select(func.count())
            .select_from(NotificationRecord)
            .where(NotificationRecord.organization_id == organization_id)
        )
    assert activity_count is not None
    assert notification_count is not None
    return activity_count, notification_count


def test_management_get_apis_are_business_scoped_non_disclosing_and_side_effect_free(
    postgres_engine: Engine,
) -> None:
    organization_id, caller_id, _, lead_case_id, observer_case_id, finding_id = (
        _seed_process_review_api_shape(postgres_engine)
    )
    before_counts = _side_effect_counts(postgres_engine, organization_id)
    client = _client_for_identity(postgres_engine, _identity(organization_id, caller_id))

    collection = client.get("/api/v1/management/review-cases?limit=10&offset=0")
    progress = client.get(f"/api/v1/management/review-cases/{lead_case_id}/progress")
    hidden_detail = client.get(f"/api/v1/management/review-cases/{observer_case_id}/progress")

    assert collection.status_code == 200
    payload = collection.json()
    assert payload["total"] == 1
    assert [item["id"] for item in payload["items"]] == [str(lead_case_id)]

    assert progress.status_code == 200
    progress_payload = progress.json()
    assert progress_payload["case"]["id"] == str(lead_case_id)
    assert [item["id"] for item in progress_payload["findings"]] == [str(finding_id)]

    assert hidden_detail.status_code == 404
    assert hidden_detail.json()["detail"] == "ReviewCase not found"
    assert _side_effect_counts(postgres_engine, organization_id) == before_counts

    with Session(postgres_engine) as session:
        lead_case = session.get(ReviewCaseRecord, lead_case_id)
        observer_case = session.get(ReviewCaseRecord, observer_case_id)
        assert lead_case is not None
        assert observer_case is not None
        assert lead_case.lifecycle == "in_progress"
        assert observer_case.lifecycle == "in_progress"


def test_system_admin_has_no_implicit_management_api_visibility(
    postgres_engine: Engine,
) -> None:
    organization_id, _, admin_id, lead_case_id, _, _ = _seed_process_review_api_shape(
        postgres_engine
    )
    client = _client_for_identity(
        postgres_engine,
        _identity(
            organization_id,
            admin_id,
            platform_role=PlatformRole.SYSTEM_ADMIN,
        ),
    )

    collection = client.get("/api/v1/management/review-cases")
    detail = client.get(f"/api/v1/management/review-cases/{lead_case_id}/progress")

    assert collection.status_code == 200
    assert collection.json()["items"] == []
    assert collection.json()["total"] == 0
    assert detail.status_code == 404
    assert detail.json()["detail"] == "ReviewCase not found"
