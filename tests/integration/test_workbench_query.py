import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from easyaudit_next.composition import build_scenario_registry
from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import PlatformRole, User
from easyaudit_next.platform.persistence.models import (
    DepartmentRecord,
    OrganizationRecord,
    UserRecord,
)
from easyaudit_next.review_core.domain.models import Scenario, ScenarioKey, ScenarioVersion
from easyaudit_next.review_core.domain.scenario_capabilities import AuthorizationContext
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry
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

NOW = datetime(2026, 8, 27, 4, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _seed_identity(
    session: Session,
    *,
    platform_role: str = "ordinary_user",
) -> tuple[OrganizationId, DepartmentId, UserId]:
    organization_id = OrganizationId(uuid4())
    department_id = DepartmentId(uuid4())
    user_id = UserId(uuid4())
    session.add(OrganizationRecord(id=organization_id, name=f"Workbench {organization_id}"))
    session.flush()
    session.add(
        DepartmentRecord(
            id=department_id,
            organization_id=organization_id,
            name="Operations",
        )
    )
    session.flush()
    session.add(
        UserRecord(
            id=user_id,
            organization_id=organization_id,
            primary_department_id=department_id,
            display_name="Workbench Caller",
            platform_role=platform_role,
        )
    )
    session.flush()
    return organization_id, department_id, user_id


def _actor(
    organization_id: OrganizationId,
    department_id: DepartmentId,
    user_id: UserId,
    *,
    platform_role: PlatformRole = PlatformRole.ORDINARY_USER,
) -> User:
    return User(
        id=user_id,
        organization_id=organization_id,
        display_name="Workbench Caller",
        platform_role=platform_role,
        primary_department_id=department_id,
    )


def _seed_scenario(
    session: Session,
    organization_id: OrganizationId,
    key: str,
) -> UUID:
    scenario_id = uuid4()
    version_id = uuid4()
    session.add(
        ScenarioRecord(
            id=scenario_id,
            organization_id=organization_id,
            key=key,
            name=key.replace("_", " ").title(),
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
    return version_id


def _case(
    session: Session,
    organization_id: OrganizationId,
    creator_id: UserId,
    version_id: UUID,
    title: str,
    *,
    lifecycle: str = "in_progress",
    planned_end_at: datetime | None = None,
) -> ReviewCaseRecord:
    record = ReviewCaseRecord(
        id=uuid4(),
        organization_id=organization_id,
        plan_id=None,
        scenario_version_id=version_id,
        title=title,
        lifecycle=lifecycle,
        planned_start_at=None,
        planned_end_at=planned_end_at,
        started_at=NOW,
        fieldwork_completed_at=None,
        closed_at=None,
        scenario_data_json={},
        created_by=creator_id,
        created_at=NOW,
    )
    session.add(record)
    session.flush()
    return record


def _finding(
    session: Session,
    organization_id: OrganizationId,
    case_id: UUID,
    raiser_id: UserId,
    title: str,
    *,
    lifecycle: str = "rectifying",
    raised_at: datetime = NOW,
) -> FindingRecord:
    record = FindingRecord(
        id=uuid4(),
        organization_id=organization_id,
        case_id=case_id,
        title=title,
        description=None,
        severity="medium",
        lifecycle=lifecycle,
        raised_by=raiser_id,
        raised_at=raised_at,
        scenario_data_json={},
    )
    session.add(record)
    session.flush()
    return record


def _action(
    session: Session,
    organization_id: OrganizationId,
    finding_id: UUID,
    title: str,
    *,
    lifecycle: str = "todo",
    due_at: datetime | None = None,
) -> ActionItemRecord:
    record = ActionItemRecord(
        id=uuid4(),
        organization_id=organization_id,
        finding_id=finding_id,
        title=title,
        lifecycle=lifecycle,
        due_at=due_at,
        completed_at=NOW if lifecycle == "done" else None,
    )
    session.add(record)
    session.flush()
    return record


def _case_member(
    session: Session,
    organization_id: OrganizationId,
    case_id: UUID,
    user_id: UserId,
    role_key: str,
) -> None:
    session.add(
        CaseMemberRecord(
            organization_id=organization_id,
            case_id=case_id,
            user_id=user_id,
            role_key=role_key,
            joined_at=NOW,
        )
    )


def _participant(
    session: Session,
    organization_id: OrganizationId,
    finding_id: UUID,
    user_id: UserId,
    role_key: str,
) -> None:
    session.add(
        FindingParticipantRecord(
            id=uuid4(),
            organization_id=organization_id,
            finding_id=finding_id,
            user_id=user_id,
            department_id=None,
            role_key=role_key,
            assigned_at=NOW,
        )
    )


def _assignee(
    session: Session,
    organization_id: OrganizationId,
    action_id: UUID,
    user_id: UserId,
    role: str,
) -> None:
    session.add(
        ActionAssigneeRecord(
            id=uuid4(),
            organization_id=organization_id,
            action_item_id=action_id,
            user_id=user_id,
            department_id=None,
            role=role,
            assigned_at=NOW,
        )
    )


class _ScopedAuthorization:
    def allows(self, permission: str, context: AuthorizationContext) -> bool:
        case_roles = {grant.role_key for grant in context.case_role_grants}
        finding_roles = {grant.role_key for grant in context.finding_role_grants}
        action_roles = {grant.role_key for grant in context.action_role_grants}
        if permission == "view_case":
            return bool(case_roles)
        if permission == "view_finding":
            return "owner" in finding_roles or "primary" in action_roles
        if permission == "verify_finding":
            return "owner" in finding_roles
        return False


class _ScopedPolicy:
    scenario = Scenario(
        key=ScenarioKey("scoped_test"),
        version=ScenarioVersion(1),
        name="Scoped Test",
    )
    authorization = _ScopedAuthorization()


def _scoped_registry() -> ScenarioRegistry:
    registry = ScenarioRegistry()
    registry.register(_ScopedPolicy())  # type: ignore[arg-type]
    return registry


def test_bulk_authorization_remains_target_scoped_within_one_case(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session, session.begin():
        organization_id, department_id, caller_id = _seed_identity(session)
        version_id = _seed_scenario(session, organization_id, "scoped_test")
        review_case = _case(
            session,
            organization_id,
            caller_id,
            version_id,
            "Same-case authorization isolation",
        )
        owner_finding = _finding(
            session,
            organization_id,
            review_case.id,
            caller_id,
            "Caller owns this Finding",
            lifecycle="verifying",
            raised_at=NOW - timedelta(hours=2),
        )
        collaborator_finding = _finding(
            session,
            organization_id,
            review_case.id,
            caller_id,
            "Caller only collaborates on this Finding",
            lifecycle="verifying",
            raised_at=NOW - timedelta(hours=1),
        )
        action_parent = _finding(
            session,
            organization_id,
            review_case.id,
            caller_id,
            "Action isolation parent",
        )
        primary_action = _action(
            session,
            organization_id,
            action_parent.id,
            "Caller is primary",
        )
        collaborator_action = _action(
            session,
            organization_id,
            action_parent.id,
            "Caller is collaborator only",
        )
        _participant(session, organization_id, owner_finding.id, caller_id, "owner")
        _participant(
            session,
            organization_id,
            collaborator_finding.id,
            caller_id,
            "collaborator",
        )
        _assignee(session, organization_id, primary_action.id, caller_id, "primary")
        _assignee(
            session,
            organization_id,
            collaborator_action.id,
            caller_id,
            "collaborator",
        )

    actor = _actor(organization_id, department_id, caller_id)
    with Session(postgres_engine) as session:
        snapshot = WorkbenchQueryService(session, _scoped_registry()).get_workbench(
            actor,
            as_of=NOW,
        )

    assert {item.id for item in snapshot.finding_responsibilities} == {owner_finding.id}
    assert {item.id for item in snapshot.verification_queue} == {owner_finding.id}
    assert {item.id for item in snapshot.action_responsibilities} == {primary_action.id}
    assert collaborator_finding.id not in {item.id for item in snapshot.finding_responsibilities}
    assert collaborator_finding.id not in {item.id for item in snapshot.verification_queue}
    assert collaborator_action.id not in {item.id for item in snapshot.action_responsibilities}


def test_process_review_workbench_projects_responsibilities_deadlines_and_privacy(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session, session.begin():
        organization_id, department_id, caller_id = _seed_identity(session)
        version_id = _seed_scenario(session, organization_id, "process_review")

        overdue_case = _case(
            session,
            organization_id,
            caller_id,
            version_id,
            "Overdue lead case",
            lifecycle="scheduled",
            planned_end_at=NOW - timedelta(days=1),
        )
        _case_member(session, organization_id, overdue_case.id, caller_id, "lead")

        due_case = _case(
            session,
            organization_id,
            caller_id,
            version_id,
            "Due-soon observer case",
            planned_end_at=NOW + timedelta(days=7),
        )
        _case_member(session, organization_id, due_case.id, caller_id, "observer")

        closed_case = _case(
            session,
            organization_id,
            caller_id,
            version_id,
            "Closed case with old deadline",
            lifecycle="closed",
            planned_end_at=NOW - timedelta(days=10),
        )
        _case_member(session, organization_id, closed_case.id, caller_id, "observer")

        owner_case = _case(
            session,
            organization_id,
            caller_id,
            version_id,
            "Finding owner case",
        )
        owner_finding = _finding(
            session,
            organization_id,
            owner_case.id,
            caller_id,
            "Owned Finding",
        )
        _participant(session, organization_id, owner_finding.id, caller_id, "owner")

        action_case = _case(
            session,
            organization_id,
            caller_id,
            version_id,
            "Action responsibility case",
        )
        action_finding = _finding(
            session,
            organization_id,
            action_case.id,
            caller_id,
            "Action parent",
        )
        due_action = _action(
            session,
            organization_id,
            action_finding.id,
            "Due exactly now",
            due_at=NOW,
        )
        overdue_action = _action(
            session,
            organization_id,
            action_finding.id,
            "Overdue action",
            due_at=NOW - timedelta(hours=1),
        )
        done_action = _action(
            session,
            organization_id,
            action_finding.id,
            "Done old action",
            lifecycle="done",
            due_at=NOW - timedelta(days=3),
        )
        null_deadline_action = _action(
            session,
            organization_id,
            action_finding.id,
            "No deadline action",
            due_at=None,
        )
        for action in (due_action, overdue_action, done_action, null_deadline_action):
            _assignee(session, organization_id, action.id, caller_id, "primary")

        verifier_case = _case(
            session,
            organization_id,
            caller_id,
            version_id,
            "Verifier case",
        )
        _case_member(session, organization_id, verifier_case.id, caller_id, "reviewer")
        authorized_verification = _finding(
            session,
            organization_id,
            verifier_case.id,
            caller_id,
            "Authorized verification",
            lifecycle="verifying",
            raised_at=NOW - timedelta(hours=4),
        )

        non_verifier_case = _case(
            session,
            organization_id,
            caller_id,
            version_id,
            "Owner but not verifier case",
        )
        unauthorized_verification = _finding(
            session,
            organization_id,
            non_verifier_case.id,
            caller_id,
            "Owner cannot verify",
            lifecycle="verifying",
            raised_at=NOW - timedelta(hours=3),
        )
        _participant(
            session,
            organization_id,
            unauthorized_verification.id,
            caller_id,
            "owner",
        )

        other_organization_id = OrganizationId(uuid4())
        other_user_id = UserId(uuid4())
        session.add(
            OrganizationRecord(
                id=other_organization_id,
                name=f"Other {other_organization_id}",
            )
        )
        session.flush()
        session.add(
            UserRecord(
                id=other_user_id,
                organization_id=other_organization_id,
                display_name="Other User",
                platform_role="ordinary_user",
            )
        )
        session.flush()
        other_version_id = _seed_scenario(session, other_organization_id, "process_review")
        other_case = _case(
            session,
            other_organization_id,
            other_user_id,
            other_version_id,
            "Other organization case",
            planned_end_at=NOW - timedelta(days=1),
        )
        _case_member(session, other_organization_id, other_case.id, other_user_id, "lead")

        system_admin_id = UserId(uuid4())
        session.add(
            UserRecord(
                id=system_admin_id,
                organization_id=organization_id,
                primary_department_id=department_id,
                display_name="Platform Admin",
                platform_role="system_admin",
            )
        )

    actor = _actor(organization_id, department_id, caller_id)
    with Session(postgres_engine) as session:
        snapshot = WorkbenchQueryService(session, build_scenario_registry()).get_workbench(
            actor,
            as_of=NOW,
        )

    case_ids = {item.id for item in snapshot.case_responsibilities}
    assert {overdue_case.id, due_case.id, closed_case.id, verifier_case.id}.issubset(case_ids)
    assert owner_case.id not in case_ids
    assert action_case.id not in case_ids
    assert other_case.id not in case_ids

    finding_ids = {item.id for item in snapshot.finding_responsibilities}
    assert owner_finding.id in finding_ids
    assert unauthorized_verification.id in finding_ids

    action_ids = {item.id for item in snapshot.action_responsibilities}
    assert action_ids == {
        due_action.id,
        overdue_action.id,
        done_action.id,
        null_deadline_action.id,
    }

    assert [item.id for item in snapshot.verification_queue] == [authorized_verification.id]
    assert unauthorized_verification.id not in {item.id for item in snapshot.verification_queue}

    assert [item.id for item in snapshot.overdue.cases] == [overdue_case.id]
    assert [item.id for item in snapshot.due_soon.cases] == [due_case.id]
    assert [item.id for item in snapshot.overdue.actions] == [overdue_action.id]
    assert [item.id for item in snapshot.due_soon.actions] == [due_action.id]
    deadline_action_ids = {
        item.id for item in (*snapshot.overdue.actions, *snapshot.due_soon.actions)
    }
    assert done_action.id not in deadline_action_ids
    assert null_deadline_action.id not in deadline_action_ids

    admin_actor = _actor(
        organization_id,
        department_id,
        system_admin_id,
        platform_role=PlatformRole.SYSTEM_ADMIN,
    )
    with Session(postgres_engine) as session:
        admin_snapshot = WorkbenchQueryService(session, build_scenario_registry()).get_workbench(
            admin_actor,
            as_of=NOW,
        )
    assert admin_snapshot.case_responsibilities == ()
    assert admin_snapshot.finding_responsibilities == ()
    assert admin_snapshot.action_responsibilities == ()
    assert admin_snapshot.verification_queue == ()


def _count_workbench_selects(
    engine: Engine,
    actor: User,
    registry: ScenarioRegistry,
) -> int:
    count = 0

    def before_cursor_execute(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal count
        if statement.lstrip().upper().startswith("SELECT"):
            count += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        with Session(engine) as session:
            WorkbenchQueryService(session, registry).get_workbench(actor, as_of=NOW)
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    return count


def test_workbench_query_count_is_category_bounded_not_resource_bounded(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine) as session, session.begin():
        organization_id, department_id, caller_id = _seed_identity(session)
        version_id = _seed_scenario(session, organization_id, "process_review")
        for index in range(5):
            review_case = _case(
                session,
                organization_id,
                caller_id,
                version_id,
                f"Small set {index}",
            )
            _case_member(session, organization_id, review_case.id, caller_id, "lead")

    actor = _actor(organization_id, department_id, caller_id)
    registry = build_scenario_registry()
    small_count = _count_workbench_selects(postgres_engine, actor, registry)

    with Session(postgres_engine) as session, session.begin():
        for index in range(5, 100):
            review_case = _case(
                session,
                organization_id,
                caller_id,
                version_id,
                f"Large set {index}",
            )
            _case_member(session, organization_id, review_case.id, caller_id, "lead")

    large_count = _count_workbench_selects(postgres_engine, actor, registry)

    assert small_count <= 8
    assert large_count == small_count
