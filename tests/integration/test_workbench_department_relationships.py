import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from easyaudit_next.composition import build_scenario_registry
from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import PlatformRole, User
from easyaudit_next.platform.persistence.models import (
    DepartmentRecord,
    OrganizationRecord,
    UserRecord,
)
from easyaudit_next.review_core.domain.scenario_capabilities import ActorKind, PermissionSource
from easyaudit_next.review_core.persistence.models import (
    FindingParticipantRecord,
    FindingRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)
from easyaudit_next.workbench.query_service import WorkbenchQueryService

NOW = datetime(2026, 8, 27, 4, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def test_department_visibility_keeps_department_membership_source(
    postgres_engine: Engine,
) -> None:
    organization_id = OrganizationId(uuid4())
    department_id = DepartmentId(uuid4())
    user_id = UserId(uuid4())
    scenario_id = uuid4()
    scenario_version_id = uuid4()
    case_id = uuid4()
    finding_id = uuid4()

    with Session(postgres_engine) as session, session.begin():
        session.add(OrganizationRecord(id=organization_id, name="Workbench Department Scope"))
        session.flush()
        session.add(
            DepartmentRecord(
                id=department_id,
                organization_id=organization_id,
                name="Responsible Department",
            )
        )
        session.flush()
        session.add(
            UserRecord(
                id=user_id,
                organization_id=organization_id,
                primary_department_id=department_id,
                display_name="Department Member",
                platform_role="ordinary_user",
            )
        )
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
                title="Department-visible case",
                lifecycle="in_progress",
                planned_start_at=None,
                planned_end_at=None,
                started_at=NOW,
                fieldwork_completed_at=None,
                closed_at=None,
                scenario_data_json={},
                created_by=user_id,
                created_at=NOW,
            )
        )
        session.flush()
        session.add(
            FindingRecord(
                id=finding_id,
                organization_id=organization_id,
                case_id=case_id,
                title="Department-visible Finding",
                description=None,
                severity="low",
                lifecycle="rectifying",
                raised_by=user_id,
                raised_at=NOW,
                scenario_data_json={},
            )
        )
        session.flush()
        session.add(
            FindingParticipantRecord(
                id=uuid4(),
                organization_id=organization_id,
                finding_id=finding_id,
                user_id=None,
                department_id=department_id,
                role_key="responsible_department",
                assigned_at=NOW,
            )
        )

    actor = User(
        id=user_id,
        organization_id=organization_id,
        display_name="Department Member",
        platform_role=PlatformRole.ORDINARY_USER,
        primary_department_id=department_id,
    )
    with Session(postgres_engine) as session:
        snapshot = WorkbenchQueryService(session, build_scenario_registry()).get_workbench(
            actor,
            as_of=NOW,
        )

    assert len(snapshot.finding_responsibilities) == 1
    relationship = snapshot.finding_responsibilities[0].relationships
    assert len(relationship) == 1
    assert relationship[0].role_key == "responsible_department"
    assert relationship[0].actor_kind is ActorKind.DEPARTMENT
    assert relationship[0].source is PermissionSource.DEPARTMENT_MEMBERSHIP
