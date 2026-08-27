import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from easyaudit_next.management.query_service import ManagementQueryService
from easyaudit_next.management.schemas import DeadlineBucket
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

NOW = datetime(2026, 8, 27, 8, 30, tzinfo=UTC)


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
    session.add(OrganizationRecord(id=organization_id, name=f"Management {organization_id}"))
    session.flush()
    session.add(
        DepartmentRecord(
            id=department_id,
            organization_id=organization_id,
            name="Management Department",
        )
    )
    session.flush()
    session.add(
        UserRecord(
            id=user_id,
            organization_id=organization_id,
            primary_department_id=department_id,
            display_name="Management Caller",
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
        display_name="Management Caller",
        platform_role=platform_role,
        primary_department_id=department_id,
    )


def _seed_scenario_versions(
    session: Session,
    organization_id: OrganizationId,
) -> tuple[UUID, UUID]:
    scenario_id = uuid4()
    version_one_id = uuid4()
    version_two_id = uuid4()
    session.add(
        ScenarioRecord(
            id=scenario_id,
            organization_id=organization_id,
            key="management_test",
            name="Management Test",
        )
    )
    session.flush()
    session.add_all(
        [
            ScenarioVersionRecord(
                id=version_one_id,
                scenario_id=scenario_id,
                organization_id=organization_id,
                version=1,
                published_at=NOW - timedelta(days=1),
            ),
            ScenarioVersionRecord(
                id=version_two_id,
                scenario_id=scenario_id,
                organization_id=organization_id,
                version=2,
                published_at=NOW,
            ),
        ]
    )
    session.flush()
    return version_one_id, version_two_id


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
        planned_start_at=NOW - timedelta(days=60),
        planned_end_at=planned_end_at,
        started_at=NOW - timedelta(days=1),
        fieldwork_completed_at=None,
        closed_at=None,
        scenario_data_json={},
        created_by=creator_id,
        created_at=NOW - timedelta(days=61),
    )
    session.add(record)
    session.flush()
    return record


def _member(
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


def _finding(
    session: Session,
    organization_id: OrganizationId,
    case_id: UUID,
    raiser_id: UserId,
    title: str,
    *,
    lifecycle: str = "rectifying",
    severity: str = "medium",
    raised_at: datetime = NOW,
) -> FindingRecord:
    record = FindingRecord(
        id=uuid4(),
        organization_id=organization_id,
        case_id=case_id,
        title=title,
        description=None,
        severity=severity,
        lifecycle=lifecycle,
        raised_by=raiser_id,
        raised_at=raised_at,
        scenario_data_json={},
    )
    session.add(record)
    session.flush()
    return record


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


def _assignee(
    session: Session,
    organization_id: OrganizationId,
    action_id: UUID,
    user_id: UserId,
    role: str = "primary",
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


class _ManagementAuthorizationV1:
    def allows(self, permission: str, context: AuthorizationContext) -> bool:
        case_roles = {grant.role_key for grant in context.case_role_grants}
        finding_roles = {grant.role_key for grant in context.finding_role_grants}
        action_roles = {grant.role_key for grant in context.action_role_grants}
        if permission == "view_case":
            return bool(case_roles)
        if permission == "manage_case_members":
            return "manage" in case_roles
        if permission == "view_finding":
            return "visible" in finding_roles or "primary" in action_roles
        return False


class _ManagementAuthorizationV2:
    def allows(self, permission: str, context: AuthorizationContext) -> bool:
        case_roles = {grant.role_key for grant in context.case_role_grants}
        if permission == "view_case":
            return bool(case_roles)
        if permission == "manage_case_members":
            return "future_manage" in case_roles
        if permission == "view_finding":
            return False
        return False


class _ManagementPolicyV1:
    scenario = Scenario(
        key=ScenarioKey("management_test"),
        version=ScenarioVersion(1),
        name="Management Test v1",
    )
    authorization = _ManagementAuthorizationV1()


class _ManagementPolicyV2:
    scenario = Scenario(
        key=ScenarioKey("management_test"),
        version=ScenarioVersion(2),
        name="Management Test v2",
    )
    authorization = _ManagementAuthorizationV2()


def _registry() -> ScenarioRegistry:
    registry = ScenarioRegistry()
    registry.register(_ManagementPolicyV1())  # type: ignore[arg-type]
    registry.register(_ManagementPolicyV2())  # type: ignore[arg-type]
    return registry


def test_external_pagination_is_over_authorized_management_set_and_exact_version(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session, session.begin():
        organization_id, department_id, caller_id = _seed_identity(session)
        version_one_id, version_two_id = _seed_scenario_versions(session, organization_id)

        def candidate(title: str, days: float, role: str, version_id: UUID) -> ReviewCaseRecord:
            review_case = _case(
                session,
                organization_id,
                caller_id,
                version_id,
                title,
                planned_end_at=NOW + timedelta(days=days),
            )
            _member(session, organization_id, review_case.id, caller_id, role)
            return review_case

        case_a = candidate("A", 1, "manage", version_one_id)
        candidate("H1", 2, "view_only", version_one_id)
        case_b = candidate("B", 3, "manage", version_one_id)
        candidate("H2", 4, "view_only", version_one_id)
        case_c = candidate("C", 5, "manage", version_one_id)
        candidate("V2 hidden", 2.5, "manage", version_two_id)

    actor = _actor(organization_id, department_id, caller_id)
    with Session(postgres_engine) as session:
        service = ManagementQueryService(session, _registry())
        page_one = service.list_review_cases(actor, limit=2, offset=0, as_of=NOW)
        page_two = service.list_review_cases(actor, limit=2, offset=2, as_of=NOW)

    assert [item.id for item in page_one.items] == [case_a.id, case_b.id]
    assert [item.id for item in page_two.items] == [case_c.id]
    assert page_one.total == 3
    assert page_two.total == 3

    with Session(postgres_engine) as session, session.begin():
        hidden_insert = _case(
            session,
            organization_id,
            caller_id,
            version_one_id,
            "H inserted",
            planned_end_at=NOW + timedelta(days=1, hours=12),
        )
        _member(session, organization_id, hidden_insert.id, caller_id, "view_only")

    with Session(postgres_engine) as session:
        service = ManagementQueryService(session, _registry())
        page_one_after = service.list_review_cases(actor, limit=2, offset=0, as_of=NOW)
        page_two_after = service.list_review_cases(actor, limit=2, offset=2, as_of=NOW)

    assert [item.id for item in page_one_after.items] == [case_a.id, case_b.id]
    assert [item.id for item in page_two_after.items] == [case_c.id]
    assert page_one_after.total == 3
    assert page_two_after.total == 3


def test_child_projection_authorizes_before_aggregating_and_keeps_deadline_semantics(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session, session.begin():
        organization_id, department_id, caller_id = _seed_identity(session)
        version_one_id, _ = _seed_scenario_versions(session, organization_id)
        review_case = _case(
            session,
            organization_id,
            caller_id,
            version_one_id,
            "Managed with hidden sibling",
            lifecycle="scheduled",
            planned_end_at=NOW - timedelta(days=1),
        )
        _member(session, organization_id, review_case.id, caller_id, "manage")

        visible_findings: list[FindingRecord] = []
        for index, lifecycle in enumerate(
            ("open", "rectifying", "verifying", "closed", "voided")
        ):
            finding = _finding(
                session,
                organization_id,
                review_case.id,
                caller_id,
                f"Visible {lifecycle}",
                lifecycle=lifecycle,
                severity="high" if lifecycle == "rectifying" else "medium",
                raised_at=NOW - timedelta(hours=10 - index),
            )
            _participant(session, organization_id, finding.id, caller_id, "visible")
            visible_findings.append(finding)
        visible = visible_findings[1]

        hidden = _finding(
            session,
            organization_id,
            review_case.id,
            caller_id,
            "Hidden Finding",
            lifecycle="verifying",
            severity="critical",
            raised_at=NOW - timedelta(hours=1),
        )

        overdue = _action(
            session,
            organization_id,
            visible.id,
            "Visible overdue",
            lifecycle="in_progress",
            due_at=NOW - timedelta(hours=1),
        )
        _assignee(session, organization_id, overdue.id, caller_id)
        done = _action(
            session,
            organization_id,
            visible.id,
            "Visible done",
            lifecycle="done",
            due_at=NOW - timedelta(days=2),
        )
        cancelled = _action(
            session,
            organization_id,
            visible.id,
            "Visible cancelled",
            lifecycle="cancelled",
            due_at=NOW - timedelta(days=3),
        )
        due_now = _action(
            session,
            organization_id,
            visible.id,
            "Visible due now",
            due_at=NOW,
        )
        due_seven_days = _action(
            session,
            organization_id,
            visible.id,
            "Visible due seven days",
            due_at=NOW + timedelta(days=7),
        )
        no_deadline = _action(
            session,
            organization_id,
            visible.id,
            "Visible no deadline",
            due_at=None,
        )
        hidden_overdue = _action(
            session,
            organization_id,
            hidden.id,
            "Hidden overdue",
            lifecycle="in_progress",
            due_at=NOW - timedelta(days=4),
        )

        closed_case = _case(
            session,
            organization_id,
            caller_id,
            version_one_id,
            "Closed old deadline",
            lifecycle="closed",
            planned_end_at=NOW - timedelta(days=30),
        )
        _member(session, organization_id, closed_case.id, caller_id, "manage")
        due_now_case = _case(
            session,
            organization_id,
            caller_id,
            version_one_id,
            "Case due now",
            lifecycle="scheduled",
            planned_end_at=NOW,
        )
        _member(session, organization_id, due_now_case.id, caller_id, "manage")
        no_deadline_case = _case(
            session,
            organization_id,
            caller_id,
            version_one_id,
            "Case without deadline",
            lifecycle="scheduled",
            planned_end_at=None,
        )
        _member(session, organization_id, no_deadline_case.id, caller_id, "manage")

    actor = _actor(organization_id, department_id, caller_id)
    with Session(postgres_engine) as session:
        service = ManagementQueryService(session, _registry())
        collection = service.list_review_cases(actor, limit=100, as_of=NOW)
        progress = service.get_progress(actor, review_case.id, as_of=NOW)

    summary = next(item for item in collection.items if item.id == review_case.id)
    assert summary.deadline_bucket is DeadlineBucket.OVERDUE
    assert summary.findings.total == 5
    assert summary.findings.open == 1
    assert summary.findings.rectifying == 1
    assert summary.findings.verifying == 1
    assert summary.findings.closed == 1
    assert summary.findings.voided == 1
    assert summary.actions.total == 6
    assert summary.actions.todo == 3
    assert summary.actions.in_progress == 1
    assert summary.actions.done == 1
    assert summary.actions.cancelled == 1
    assert summary.actions.overdue == 1
    assert summary.actions.due_soon == 2

    summaries = {item.id: item for item in collection.items}
    assert summaries[closed_case.id].deadline_bucket is DeadlineBucket.NONE
    assert summaries[due_now_case.id].deadline_bucket is DeadlineBucket.DUE_SOON
    assert summaries[no_deadline_case.id].deadline_bucket is DeadlineBucket.NONE

    assert [item.id for item in progress.findings] == [item.id for item in visible_findings]
    assert [item.id for item in progress.overdue_actions] == [overdue.id]
    assert [item.id for item in progress.due_soon_actions] == [due_now.id, due_seven_days.id]
    assert hidden.id not in {item.id for item in progress.findings}
    assert hidden_overdue.id not in {item.id for item in progress.overdue_actions}
    assert done.id not in {item.id for item in progress.overdue_actions}
    assert cancelled.id not in {item.id for item in progress.overdue_actions}
    assert no_deadline.id not in {item.id for item in progress.due_soon_actions}


def test_management_scope_does_not_inherit_platform_admin_or_known_uuid_access(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session, session.begin():
        organization_id, department_id, caller_id = _seed_identity(session)
        version_one_id, _ = _seed_scenario_versions(session, organization_id)
        view_only = _case(
            session,
            organization_id,
            caller_id,
            version_one_id,
            "View only",
        )
        _member(session, organization_id, view_only.id, caller_id, "view_only")

        admin_id = UserId(uuid4())
        session.add(
            UserRecord(
                id=admin_id,
                organization_id=organization_id,
                primary_department_id=department_id,
                display_name="Platform Admin",
                platform_role="system_admin",
            )
        )

        other_organization_id, other_department_id, other_user_id = _seed_identity(session)
        other_version_one_id, _ = _seed_scenario_versions(session, other_organization_id)
        other_case = _case(
            session,
            other_organization_id,
            other_user_id,
            other_version_one_id,
            "Other organization",
        )
        _member(session, other_organization_id, other_case.id, other_user_id, "manage")

    actor = _actor(organization_id, department_id, caller_id)
    with Session(postgres_engine) as session:
        service = ManagementQueryService(session, _registry())
        assert service.list_review_cases(actor, as_of=NOW).items == ()
        with pytest.raises(LookupError, match="Managed ReviewCase not found"):
            service.get_progress(actor, view_only.id, as_of=NOW)
        with pytest.raises(LookupError, match="Managed ReviewCase not found"):
            service.get_progress(actor, other_case.id, as_of=NOW)
        assert service.list_review_cases(
            actor,
            review_plan_id=uuid4(),
            as_of=NOW,
        ).items == ()

    admin = _actor(
        organization_id,
        department_id,
        admin_id,
        platform_role=PlatformRole.SYSTEM_ADMIN,
    )
    with Session(postgres_engine) as session:
        admin_page = ManagementQueryService(session, _registry()).list_review_cases(
            admin,
            as_of=NOW,
        )
    assert admin_page.items == ()
    assert admin_page.total == 0

    other_actor = _actor(other_organization_id, other_department_id, other_user_id)
    with Session(postgres_engine) as session:
        other_page = ManagementQueryService(session, _registry()).list_review_cases(
            other_actor,
            as_of=NOW,
        )
    assert [item.id for item in other_page.items] == [other_case.id]


def _count_management_selects(engine: Engine, actor: User) -> int:
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
            ManagementQueryService(session, _registry()).list_review_cases(
                actor,
                limit=100,
                as_of=NOW,
            )
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    return count


def test_management_query_count_is_category_bounded_from_five_to_one_hundred(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine) as session, session.begin():
        organization_id, department_id, caller_id = _seed_identity(session)
        version_one_id, _ = _seed_scenario_versions(session, organization_id)

        def add_managed_case(index: int) -> None:
            review_case = _case(
                session,
                organization_id,
                caller_id,
                version_one_id,
                f"Managed {index:03d}",
                planned_end_at=NOW + timedelta(days=index + 1),
            )
            _member(session, organization_id, review_case.id, caller_id, "manage")
            finding = _finding(
                session,
                organization_id,
                review_case.id,
                caller_id,
                f"Visible {index:03d}",
            )
            _participant(session, organization_id, finding.id, caller_id, "visible")
            action = _action(
                session,
                organization_id,
                finding.id,
                f"Action {index:03d}",
                due_at=NOW + timedelta(days=1),
            )
            _assignee(session, organization_id, action.id, caller_id)

        for index in range(5):
            add_managed_case(index)

    actor = _actor(organization_id, department_id, caller_id)
    small_count = _count_management_selects(postgres_engine, actor)

    with Session(postgres_engine) as session, session.begin():
        for index in range(5, 100):
            review_case = _case(
                session,
                organization_id,
                caller_id,
                version_one_id,
                f"Managed {index:03d}",
                planned_end_at=NOW + timedelta(days=index + 1),
            )
            _member(session, organization_id, review_case.id, caller_id, "manage")
            finding = _finding(
                session,
                organization_id,
                review_case.id,
                caller_id,
                f"Visible {index:03d}",
            )
            _participant(session, organization_id, finding.id, caller_id, "visible")
            action = _action(
                session,
                organization_id,
                finding.id,
                f"Action {index:03d}",
                due_at=NOW + timedelta(days=1),
            )
            _assignee(session, organization_id, action.id, caller_id)

    large_count = _count_management_selects(postgres_engine, actor)

    assert small_count <= 8
    assert large_count == small_count
