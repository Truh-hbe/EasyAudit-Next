import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, create_engine, event
from sqlalchemy.engine.interfaces import DBAPICursor, ExecutionContext
from sqlalchemy.orm import Session

from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import PlatformRole, User
from easyaudit_next.platform.persistence.models import (
    DepartmentRecord,
    OrganizationRecord,
    UserRecord,
)
from easyaudit_next.review_core.application.authorization import (
    build_authorization_context,
    build_rectification_authorization_context,
)
from easyaudit_next.review_core.domain.ids import ActionItemId, FindingId, ReviewCaseId
from easyaudit_next.review_core.persistence.models import (
    ActionAssigneeRecord,
    ActionItemRecord,
    FindingParticipantRecord,
    FindingRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)
from easyaudit_next.review_core.persistence.rectification_repositories import (
    SqlAlchemyRectificationRepository,
)

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


@dataclass(frozen=True, slots=True)
class Graph:
    organization_id: OrganizationId
    actor: User
    case_id: ReviewCaseId
    finding_ids: tuple[FindingId, ...]
    action_ids: tuple[ActionItemId, ...]


def _seed(engine: Engine, *, findings: int, actions_per_finding: int) -> Graph:
    """One Case whose participants/assignees mix the actor, its department and a stranger."""

    organization_id = OrganizationId(uuid4())
    actor_id, other_id = uuid4(), uuid4()
    department_id, other_department_id = uuid4(), uuid4()
    scenario_id, version_id, case_id = uuid4(), uuid4(), uuid4()
    finding_ids = [uuid4() for _ in range(findings)]
    action_ids: list[UUID] = []

    with Session(engine) as session, session.begin():
        session.add(OrganizationRecord(id=organization_id, name=f"Batch Org {organization_id}"))
        session.flush()
        session.add_all(
            [
                DepartmentRecord(id=department_id, organization_id=organization_id, name="Dept"),
                DepartmentRecord(
                    id=other_department_id, organization_id=organization_id, name="Other Dept"
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                UserRecord(
                    id=actor_id,
                    organization_id=organization_id,
                    primary_department_id=department_id,
                    display_name="Actor",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=other_id,
                    organization_id=organization_id,
                    display_name="Other",
                    platform_role="ordinary_user",
                ),
            ]
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
                title="Batch reads",
                lifecycle="in_progress",
                planned_start_at=None,
                planned_end_at=None,
                started_at=NOW,
                fieldwork_completed_at=None,
                closed_at=None,
                scenario_data_json={},
                created_by=actor_id,
                created_at=NOW,
            )
        )
        session.flush()
        for index, finding_id in enumerate(finding_ids):
            session.add(
                FindingRecord(
                    id=finding_id,
                    organization_id=organization_id,
                    case_id=case_id,
                    title=f"Finding {index}",
                    description=None,
                    severity="high",
                    lifecycle="rectifying",
                    raised_by=actor_id,
                    raised_at=NOW,
                    scenario_data_json={},
                )
            )
        session.flush()
        for index, finding_id in enumerate(finding_ids):
            for user_id, department, role_key in (
                (actor_id if index % 2 == 0 else other_id, None, "owner"),
                (None, department_id if index % 3 == 0 else other_department_id, "reviewer"),
            ):
                session.add(
                    FindingParticipantRecord(
                        id=uuid4(),
                        organization_id=organization_id,
                        finding_id=finding_id,
                        user_id=user_id,
                        department_id=department,
                        role_key=role_key,
                        assigned_at=NOW,
                    )
                )
            for slot in range(actions_per_finding):
                action_id = uuid4()
                action_ids.append(action_id)
                session.add(
                    ActionItemRecord(
                        id=action_id,
                        organization_id=organization_id,
                        finding_id=finding_id,
                        title=f"Action {index}-{slot}",
                        lifecycle="todo",
                        due_at=None,
                    )
                )
        session.flush()
        for index, action_id in enumerate(action_ids):
            for user_id, department, role in (
                (actor_id if index % 2 == 0 else other_id, None, "primary"),
                (None, department_id if index % 3 == 0 else other_department_id, "collaborator"),
            ):
                session.add(
                    ActionAssigneeRecord(
                        id=uuid4(),
                        organization_id=organization_id,
                        action_item_id=action_id,
                        user_id=user_id,
                        department_id=department,
                        role=role,
                        assigned_at=NOW,
                    )
                )

    return Graph(
        organization_id=organization_id,
        actor=User(
            id=UserId(actor_id),
            organization_id=organization_id,
            display_name="Actor",
            platform_role=PlatformRole.ORDINARY_USER,
            primary_department_id=DepartmentId(department_id),
        ),
        case_id=ReviewCaseId(case_id),
        finding_ids=tuple(FindingId(i) for i in finding_ids),
        action_ids=tuple(ActionItemId(i) for i in action_ids),
    )


def test_batch_reads_match_per_object_reads(postgres_engine: Engine) -> None:
    graph = _seed(postgres_engine, findings=5, actions_per_finding=2)
    with Session(postgres_engine) as session:
        repository = SqlAlchemyRectificationRepository(session)
        org = graph.organization_id

        participants = repository.list_finding_participants_for_findings(org, graph.finding_ids)
        assert len(participants) == 10
        assert set(participants) == {
            p for f in graph.finding_ids for p in repository.list_finding_participants(org, f)
        }

        actions = repository.list_action_items_for_findings(org, graph.finding_ids)
        assert len(actions) == 10
        assert set(actions) == {
            a for f in graph.finding_ids for a in repository.list_action_items(org, f)
        }

        assignees = repository.list_action_assignees_for_actions(org, graph.action_ids)
        assert len(assignees) == 20
        assert set(assignees) == {
            a for i in graph.action_ids for a in repository.list_action_assignees(org, i)
        }

        # a subset only returns that subset
        assert {
            a.id for a in repository.list_action_items_for_findings(org, graph.finding_ids[:1])
        } == {a.id for a in repository.list_action_items(org, graph.finding_ids[0])}


def test_batch_reads_handle_empty_sets_without_querying(postgres_engine: Engine) -> None:
    graph = _seed(postgres_engine, findings=1, actions_per_finding=1)
    statements: list[str] = []

    def count(
        conn: Connection,
        cursor: DBAPICursor,
        statement: str,
        parameters: object,
        context: ExecutionContext | None,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    with Session(postgres_engine) as session:
        repository = SqlAlchemyRectificationRepository(session)
        event.listen(postgres_engine, "before_cursor_execute", count)
        try:
            org = graph.organization_id
            assert repository.list_finding_participants_for_findings(org, ()) == ()
            assert repository.list_action_items_for_findings(org, ()) == ()
            assert repository.list_action_assignees_for_actions(org, ()) == ()
        finally:
            event.remove(postgres_engine, "before_cursor_execute", count)
    assert statements == []


def test_batch_reads_do_not_leak_across_organizations(postgres_engine: Engine) -> None:
    mine = _seed(postgres_engine, findings=2, actions_per_finding=2)
    foreign = _seed(postgres_engine, findings=2, actions_per_finding=2)
    with Session(postgres_engine) as session:
        repository = SqlAlchemyRectificationRepository(session)
        org = mine.organization_id

        assert repository.list_finding_participants_for_findings(org, foreign.finding_ids) == ()
        assert repository.list_action_items_for_findings(org, foreign.finding_ids) == ()
        assert repository.list_action_assignees_for_actions(org, foreign.action_ids) == ()

        mixed = repository.list_finding_participants_for_findings(
            org, (*mine.finding_ids, *foreign.finding_ids)
        )
        assert {p.finding_id for p in mixed} == set(mine.finding_ids)
        mixed_assignees = repository.list_action_assignees_for_actions(
            org, (*mine.action_ids, *foreign.action_ids)
        )
        assert {a.action_item_id for a in mixed_assignees} == set(mine.action_ids)


def test_context_grants_come_from_the_actors_own_relationships(postgres_engine: Engine) -> None:
    graph = _seed(postgres_engine, findings=5, actions_per_finding=2)
    with Session(postgres_engine) as session:
        repository = SqlAlchemyRectificationRepository(session)
        context = build_rectification_authorization_context(repository, graph.actor, graph.case_id)
        assert {(g.role_key, g.actor_kind.value) for g in context.finding_role_grants} == {
            ("owner", "user"),
            ("reviewer", "department"),
        }
        assert {(g.role_key, g.actor_kind.value) for g in context.action_role_grants} == {
            ("primary", "user"),
            ("collaborator", "department"),
        }

        # finding 1 / action 1: owner is the stranger, department is the other one
        narrowed = build_rectification_authorization_context(
            repository,
            graph.actor,
            graph.case_id,
            finding_id=graph.finding_ids[1],
            action_item_id=graph.action_ids[1],
        )
        assert narrowed.finding_role_grants == frozenset()
        assert narrowed.action_role_grants == frozenset()


def _count_context_queries(engine: Engine, graph: Graph) -> int:
    statements: list[str] = []

    def count(
        conn: Connection,
        cursor: DBAPICursor,
        statement: str,
        parameters: object,
        context: ExecutionContext | None,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    with Session(engine) as session:
        repository = SqlAlchemyRectificationRepository(session)
        event.listen(engine, "before_cursor_execute", count)
        try:
            build_rectification_authorization_context(repository, graph.actor, graph.case_id)
        finally:
            event.remove(engine, "before_cursor_execute", count)
    return len(statements)


def test_context_query_count_does_not_grow_with_findings_or_actions(
    postgres_engine: Engine,
) -> None:
    small = _seed(postgres_engine, findings=1, actions_per_finding=1)
    large = _seed(postgres_engine, findings=5, actions_per_finding=2)

    small_count = _count_context_queries(postgres_engine, small)
    large_count = _count_context_queries(postgres_engine, large)

    # members, findings, participants, findings again (rectification), actions, assignees
    assert small_count == large_count == 6


def test_base_context_query_count_is_constant(postgres_engine: Engine) -> None:
    graph = _seed(postgres_engine, findings=5, actions_per_finding=1)
    statements: list[str] = []

    def count(
        conn: Connection,
        cursor: DBAPICursor,
        statement: str,
        parameters: object,
        context: ExecutionContext | None,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    with Session(postgres_engine) as session:
        repository = SqlAlchemyRectificationRepository(session)
        event.listen(postgres_engine, "before_cursor_execute", count)
        try:
            build_authorization_context(repository, graph.actor, graph.case_id)
        finally:
            event.remove(postgres_engine, "before_cursor_execute", count)
    assert len(statements) == 3
