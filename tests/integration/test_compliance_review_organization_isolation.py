import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from easyaudit_next.platform.domain.ids import OrganizationId
from easyaudit_next.platform.persistence.models import (
    DepartmentRecord,
    OrganizationRecord,
    UserRecord,
)
from easyaudit_next.review_core.persistence.models import (
    ActionAssigneeRecord,
    ActionItemRecord,
    CaseMemberRecord,
    FindingParticipantRecord,
    FindingRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _seed_compliance_graph(engine: Engine) -> dict[str, object]:
    organization_a = OrganizationId(uuid4())
    organization_b = OrganizationId(uuid4())
    user_a = uuid4()
    user_b = uuid4()
    department_b = uuid4()
    scenario_id = uuid4()
    scenario_version_id = uuid4()
    case_id = uuid4()
    finding_id = uuid4()
    action_id = uuid4()

    with Session(engine) as session, session.begin():
        session.add_all(
            [
                OrganizationRecord(
                    id=organization_a,
                    name=f"Compliance Organization A {organization_a}",
                ),
                OrganizationRecord(
                    id=organization_b,
                    name=f"Compliance Organization B {organization_b}",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                UserRecord(
                    id=user_a,
                    organization_id=organization_a,
                    display_name="Compliance User A",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=user_b,
                    organization_id=organization_b,
                    display_name="Foreign User B",
                    platform_role="ordinary_user",
                ),
                DepartmentRecord(
                    id=department_b,
                    organization_id=organization_b,
                    name="Foreign Department B",
                ),
            ]
        )
        session.flush()
        session.add(
            ScenarioRecord(
                id=scenario_id,
                organization_id=organization_a,
                key="compliance_review",
                name="Compliance Review",
            )
        )
        session.flush()
        session.add(
            ScenarioVersionRecord(
                id=scenario_version_id,
                scenario_id=scenario_id,
                organization_id=organization_a,
                version=1,
                published_at=NOW,
            )
        )
        session.flush()
        session.add(
            ReviewCaseRecord(
                id=case_id,
                organization_id=organization_a,
                plan_id=None,
                scenario_version_id=scenario_version_id,
                title="Compliance Organization Isolation",
                lifecycle="in_progress",
                planned_start_at=None,
                planned_end_at=None,
                started_at=NOW,
                fieldwork_completed_at=None,
                closed_at=None,
                scenario_data_json={
                    "standard_reference": "ISO 9001:2015",
                    "scope_summary": "Organization boundary proof",
                },
                created_by=user_a,
                created_at=NOW,
            )
        )
        session.flush()
        session.add(
            FindingRecord(
                id=finding_id,
                organization_id=organization_a,
                case_id=case_id,
                title="Compliance nonconformity",
                description=None,
                severity="high",
                lifecycle="rectifying",
                raised_by=user_a,
                raised_at=NOW,
                scenario_data_json={
                    "criterion_reference": "8.5.1",
                    "finding_type": "nonconformity",
                },
            )
        )
        session.flush()
        session.add(
            ActionItemRecord(
                id=action_id,
                organization_id=organization_a,
                finding_id=finding_id,
                title="Correct compliance gap",
                lifecycle="todo",
                due_at=None,
            )
        )

    return {
        "organization_a": organization_a,
        "user_b": user_b,
        "department_b": department_b,
        "case_id": case_id,
        "finding_id": finding_id,
        "action_id": action_id,
    }


@pytest.mark.parametrize(
    ("target", "actor_kind"),
    [
        ("case", "user"),
        ("finding", "user"),
        ("finding", "department"),
        ("action", "user"),
        ("action", "department"),
    ],
)
def test_compliance_graph_rejects_cross_organization_relationships(
    postgres_engine: Engine,
    target: str,
    actor_kind: str,
) -> None:
    graph = _seed_compliance_graph(postgres_engine)

    with Session(postgres_engine) as session:
        if target == "case":
            record = CaseMemberRecord(
                organization_id=graph["organization_a"],
                case_id=graph["case_id"],
                user_id=graph["user_b"],
                role_key="observer",
                joined_at=NOW,
            )
        elif target == "finding":
            record = FindingParticipantRecord(
                id=uuid4(),
                organization_id=graph["organization_a"],
                finding_id=graph["finding_id"],
                user_id=graph["user_b"] if actor_kind == "user" else None,
                department_id=(
                    graph["department_b"] if actor_kind == "department" else None
                ),
                role_key=("owner" if actor_kind == "user" else "responsible_department"),
                assigned_at=NOW,
            )
        else:
            record = ActionAssigneeRecord(
                id=uuid4(),
                organization_id=graph["organization_a"],
                action_item_id=graph["action_id"],
                user_id=graph["user_b"] if actor_kind == "user" else None,
                department_id=(
                    graph["department_b"] if actor_kind == "department" else None
                ),
                role="primary" if actor_kind == "user" else "collaborator",
                assigned_at=NOW,
            )

        session.add(record)
        with pytest.raises(IntegrityError):
            session.flush()
