import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from easyaudit_next.collaboration.nudge import ManualNudgeService
from easyaudit_next.composition import build_scenario_registry
from easyaudit_next.management.query_service import ManagementQueryService
from easyaudit_next.notifications.models import NotificationKind
from easyaudit_next.notifications.persistence import (
    NotificationRecord,
    SqlAlchemyNotificationRepository,
)
from easyaudit_next.notifications.service import NotificationService
from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.persistence.models import (
    DepartmentRecord,
    OrganizationRecord,
    UserRecord,
)
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
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
from easyaudit_next.workbench.query_service import WorkbenchQueryService

NOW = datetime(2026, 8, 29, 13, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


@dataclass(frozen=True, slots=True)
class ReuseGraph:
    organization_id: OrganizationId
    lead_id: UserId
    owner_id: UserId
    executor_id: UserId
    unrelated_id: UserId
    case_id: UUID
    finding_id: UUID
    action_id: UUID


def _seed_reuse_graph(engine: Engine) -> ReuseGraph:
    organization_id = OrganizationId(uuid4())
    department_id = DepartmentId(uuid4())
    lead_id = UserId(uuid4())
    owner_id = UserId(uuid4())
    executor_id = UserId(uuid4())
    unrelated_id = UserId(uuid4())
    scenario_id = uuid4()
    version_id = uuid4()
    case_id = uuid4()
    finding_id = uuid4()
    action_id = uuid4()

    with Session(engine) as session, session.begin():
        session.add(
            OrganizationRecord(
                id=organization_id,
                name=f"Compliance M3 reuse {organization_id}",
            )
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
                    display_name="Compliance Lead",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=owner_id,
                    organization_id=organization_id,
                    primary_department_id=department_id,
                    display_name="Compliance Owner",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=executor_id,
                    organization_id=organization_id,
                    display_name="Compliance Executor",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=unrelated_id,
                    organization_id=organization_id,
                    display_name="Unrelated User",
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
                id=version_id,
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
                scenario_version_id=version_id,
                title="Compliance M3 reuse proof",
                lifecycle="in_progress",
                planned_start_at=NOW - timedelta(days=1),
                planned_end_at=NOW + timedelta(days=5),
                started_at=NOW - timedelta(hours=2),
                fieldwork_completed_at=None,
                closed_at=None,
                scenario_data_json={
                    "standard_reference": "ISO 9001:2015",
                    "scope_summary": "Shared M3 capability proof",
                },
                created_by=lead_id,
                created_at=NOW - timedelta(days=1),
            )
        )
        session.flush()
        session.add(
            CaseMemberRecord(
                organization_id=organization_id,
                case_id=case_id,
                user_id=lead_id,
                role_key="lead",
                joined_at=NOW - timedelta(days=1),
            )
        )
        session.flush()
        session.add(
            FindingRecord(
                id=finding_id,
                organization_id=organization_id,
                case_id=case_id,
                title="Compliance nonconformity",
                description=None,
                severity="high",
                lifecycle="rectifying",
                raised_by=lead_id,
                raised_at=NOW - timedelta(hours=1),
                scenario_data_json={
                    "criterion_reference": "8.5.1",
                    "finding_type": "nonconformity",
                },
            )
        )
        session.flush()
        session.add_all(
            [
                FindingParticipantRecord(
                    id=uuid4(),
                    organization_id=organization_id,
                    finding_id=finding_id,
                    user_id=owner_id,
                    department_id=None,
                    role_key="owner",
                    assigned_at=NOW,
                ),
                FindingParticipantRecord(
                    id=uuid4(),
                    organization_id=organization_id,
                    finding_id=finding_id,
                    user_id=None,
                    department_id=department_id,
                    role_key="responsible_department",
                    assigned_at=NOW,
                ),
            ]
        )
        session.flush()
        session.add(
            ActionItemRecord(
                id=action_id,
                organization_id=organization_id,
                finding_id=finding_id,
                title="Correct compliance gap",
                lifecycle="todo",
                due_at=NOW + timedelta(days=2),
                completed_at=None,
            )
        )
        session.flush()
        session.add(
            ActionAssigneeRecord(
                id=uuid4(),
                organization_id=organization_id,
                action_item_id=action_id,
                user_id=executor_id,
                department_id=None,
                role="primary",
                assigned_at=NOW,
            )
        )

    return ReuseGraph(
        organization_id=organization_id,
        lead_id=lead_id,
        owner_id=owner_id,
        executor_id=executor_id,
        unrelated_id=unrelated_id,
        case_id=case_id,
        finding_id=finding_id,
        action_id=action_id,
    )


def test_compliance_resources_reuse_workbench_projection(
    postgres_engine: Engine,
) -> None:
    graph = _seed_reuse_graph(postgres_engine)
    registry = build_scenario_registry()

    with Session(postgres_engine) as session:
        users = SqlAlchemyUserRepository(session)
        lead = users.get(graph.lead_id)
        owner = users.get(graph.owner_id)
        executor = users.get(graph.executor_id)
        unrelated = users.get(graph.unrelated_id)
        assert lead is not None
        assert owner is not None
        assert executor is not None
        assert unrelated is not None

        service = WorkbenchQueryService(session, registry)
        lead_view = service.get_workbench(lead, as_of=NOW)
        owner_view = service.get_workbench(owner, as_of=NOW)
        executor_view = service.get_workbench(executor, as_of=NOW)
        unrelated_view = service.get_workbench(unrelated, as_of=NOW)

    assert {item.id for item in lead_view.case_responsibilities} == {graph.case_id}
    assert {item.id for item in owner_view.finding_responsibilities} == {graph.finding_id}
    assert {item.id for item in executor_view.action_responsibilities} == {graph.action_id}
    assert unrelated_view.case_responsibilities == ()
    assert unrelated_view.finding_responsibilities == ()
    assert unrelated_view.action_responsibilities == ()


def test_compliance_resources_reuse_management_projection(
    postgres_engine: Engine,
) -> None:
    graph = _seed_reuse_graph(postgres_engine)

    with Session(postgres_engine) as session:
        lead = SqlAlchemyUserRepository(session).get(graph.lead_id)
        assert lead is not None
        service = ManagementQueryService(session, build_scenario_registry())
        collection = service.list_review_cases(lead, as_of=NOW)
        progress = service.get_progress(lead, graph.case_id, as_of=NOW)

    assert collection.total == 1
    assert collection.items[0].id == graph.case_id
    assert collection.items[0].scenario_key == "compliance_review"
    assert collection.items[0].scenario_version == 1
    assert collection.items[0].findings.total == 1
    assert collection.items[0].findings.rectifying == 1
    assert collection.items[0].actions.total == 1
    assert progress.case.id == graph.case_id
    assert [item.id for item in progress.findings] == [graph.finding_id]
    assert progress.findings[0].actions.todo == 1


def test_compliance_reuses_manual_nudge_and_notification_delivery(
    postgres_engine: Engine,
) -> None:
    graph = _seed_reuse_graph(postgres_engine)

    with Session(postgres_engine) as session:
        lead = SqlAlchemyUserRepository(session).get(graph.lead_id)
        assert lead is not None
        service = ManualNudgeService(
            session,
            build_scenario_registry(),
            NotificationService(SqlAlchemyNotificationRepository(session)),
        )
        finding_result = service.nudge_finding(
            lead,
            graph.finding_id,
            occurred_at=NOW,
        )
        action_result = service.nudge_action_item(
            lead,
            graph.action_id,
            occurred_at=NOW,
        )
        session.commit()

    assert finding_result.recipient_count == 1
    assert action_result.recipient_count == 1

    with Session(postgres_engine) as verification:
        rows = tuple(
            verification.scalars(
                select(NotificationRecord).where(
                    NotificationRecord.organization_id == graph.organization_id,
                    NotificationRecord.origin_activity_id.in_(
                        [finding_result.activity_id, action_result.activity_id]
                    ),
                )
            )
        )

    assert len(rows) == 2
    finding_notification = next(
        row
        for row in rows
        if row.kind == NotificationKind.MANUAL_FINDING_NUDGE.value
    )
    action_notification = next(
        row
        for row in rows
        if row.kind == NotificationKind.MANUAL_ACTION_NUDGE.value
    )
    assert finding_notification.recipient_user_id == graph.owner_id
    assert finding_notification.finding_id == graph.finding_id
    assert finding_notification.action_item_id is None
    assert action_notification.recipient_user_id == graph.executor_id
    assert action_notification.action_item_id == graph.action_id
    assert action_notification.finding_id is None
