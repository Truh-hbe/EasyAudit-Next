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
from easyaudit_next.review_case_queries.query_service import (
    SELECT_QUERY_BOUND,
    ReviewCaseCollectionQueryService,
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

NOW = datetime(2026, 8, 28, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _seed_identity(
    session: Session,
) -> tuple[OrganizationId, DepartmentId, UserId, UserId]:
    organization_id = OrganizationId(uuid4())
    department_id = DepartmentId(uuid4())
    caller_id = UserId(uuid4())
    other_id = UserId(uuid4())
    session.add(OrganizationRecord(id=organization_id, name=f"Case query {organization_id}"))
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
                id=caller_id,
                organization_id=organization_id,
                primary_department_id=department_id,
                display_name="Collection Caller",
                platform_role="ordinary_user",
            ),
            UserRecord(
                id=other_id,
                organization_id=organization_id,
                display_name="Hidden Relationship User",
                platform_role="ordinary_user",
            ),
        ]
    )
    session.flush()
    return organization_id, department_id, caller_id, other_id


def _actor(
    organization_id: OrganizationId,
    department_id: DepartmentId,
    user_id: UserId,
) -> User:
    return User(
        id=user_id,
        organization_id=organization_id,
        display_name="Collection Caller",
        platform_role=PlatformRole.ORDINARY_USER,
        primary_department_id=department_id,
    )


def _seed_process_review_version(
    session: Session,
    organization_id: OrganizationId,
) -> UUID:
    scenario_id = uuid4()
    version_id = uuid4()
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
    return version_id


def _case(
    session: Session,
    organization_id: OrganizationId,
    creator_id: UserId,
    version_id: UUID,
    title: str,
    *,
    created_at: datetime,
    case_id: UUID | None = None,
) -> ReviewCaseRecord:
    record = ReviewCaseRecord(
        id=case_id or uuid4(),
        organization_id=organization_id,
        plan_id=None,
        scenario_version_id=version_id,
        title=title,
        lifecycle="in_progress",
        planned_start_at=None,
        planned_end_at=None,
        started_at=NOW,
        fieldwork_completed_at=None,
        closed_at=None,
        scenario_data_json={},
        created_by=creator_id,
        created_at=created_at,
    )
    session.add(record)
    session.flush()
    return record


def _case_member(
    session: Session,
    organization_id: OrganizationId,
    case_id: UUID,
    user_id: UserId,
    role_key: str = "observer",
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
) -> FindingRecord:
    record = FindingRecord(
        id=uuid4(),
        organization_id=organization_id,
        case_id=case_id,
        title=title,
        description=None,
        severity="medium",
        lifecycle="rectifying",
        raised_by=raiser_id,
        raised_at=NOW,
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
) -> ActionItemRecord:
    record = ActionItemRecord(
        id=uuid4(),
        organization_id=organization_id,
        finding_id=finding_id,
        title=title,
        lifecycle="todo",
        due_at=None,
        completed_at=None,
    )
    session.add(record)
    session.flush()
    return record


def _user_participant(
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


def _department_participant(
    session: Session,
    organization_id: OrganizationId,
    finding_id: UUID,
    department_id: DepartmentId,
    role_key: str,
) -> None:
    session.add(
        FindingParticipantRecord(
            id=uuid4(),
            organization_id=organization_id,
            finding_id=finding_id,
            user_id=None,
            department_id=department_id,
            role_key=role_key,
            assigned_at=NOW,
        )
    )


def _user_action_assignee(
    session: Session,
    organization_id: OrganizationId,
    action_item_id: UUID,
    user_id: UserId,
    role: str = "primary",
) -> None:
    session.add(
        ActionAssigneeRecord(
            id=uuid4(),
            organization_id=organization_id,
            action_item_id=action_item_id,
            user_id=user_id,
            department_id=None,
            role=role,
            assigned_at=NOW,
        )
    )


def _count_collection_selects(
    engine: Engine,
    actor: User,
    *,
    limit: int = 50,
    offset: int = 0,
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
            ReviewCaseCollectionQueryService(
                session,
                build_scenario_registry(),
            ).list_review_cases(actor, limit=limit, offset=offset)
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    return count


def test_collection_bulk_context_matches_case_visibility_sources(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session, session.begin():
        organization_id, department_id, caller_id, other_id = _seed_identity(session)
        version_id = _seed_process_review_version(session, organization_id)

        direct_case = _case(
            session,
            organization_id,
            caller_id,
            version_id,
            "Direct case relationship",
            created_at=NOW + timedelta(minutes=4),
        )
        _case_member(session, organization_id, direct_case.id, caller_id)

        finding_case = _case(
            session,
            organization_id,
            caller_id,
            version_id,
            "Finding relationship",
            created_at=NOW + timedelta(minutes=3),
        )
        owned = _finding(
            session,
            organization_id,
            finding_case.id,
            other_id,
            "Owned Finding",
        )
        _user_participant(session, organization_id, owned.id, caller_id, "owner")

        department_case = _case(
            session,
            organization_id,
            caller_id,
            version_id,
            "Department relationship",
            created_at=NOW + timedelta(minutes=2),
        )
        department_finding = _finding(
            session,
            organization_id,
            department_case.id,
            other_id,
            "Department Finding",
        )
        _department_participant(
            session,
            organization_id,
            department_finding.id,
            department_id,
            "responsible_department",
        )

        action_case = _case(
            session,
            organization_id,
            caller_id,
            version_id,
            "Action-only relationship",
            created_at=NOW + timedelta(minutes=1),
        )
        action_finding = _finding(
            session,
            organization_id,
            action_case.id,
            other_id,
            "Action parent Finding",
        )
        assigned_action = _action(
            session,
            organization_id,
            action_finding.id,
            "Caller assigned Action",
        )
        _user_action_assignee(
            session,
            organization_id,
            assigned_action.id,
            caller_id,
        )

        hidden_case = _case(
            session,
            organization_id,
            caller_id,
            version_id,
            "No caller relationship",
            created_at=NOW,
        )
        hidden_finding = _finding(
            session,
            organization_id,
            hidden_case.id,
            other_id,
            "Other user's Finding",
        )
        _user_participant(session, organization_id, hidden_finding.id, other_id, "owner")

    actor = _actor(organization_id, department_id, caller_id)
    with Session(postgres_engine) as session:
        collection = ReviewCaseCollectionQueryService(
            session,
            build_scenario_registry(),
        ).list_review_cases(actor)

    assert [item.id for item in collection.items] == [
        direct_case.id,
        finding_case.id,
        department_case.id,
        action_case.id,
    ]
    assert collection.total == 4
    assert action_case.id in {item.id for item in collection.items}
    assert hidden_case.id not in {item.id for item in collection.items}


def test_hidden_candidates_never_occupy_page_slots_or_authorized_total(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session, session.begin():
        organization_id, department_id, caller_id, other_id = _seed_identity(session)
        version_id = _seed_process_review_version(session, organization_id)
        ordered: list[ReviewCaseRecord] = []
        for index, (title, visible) in enumerate(
            (("A", True), ("H1", False), ("B", True), ("H2", False), ("C", True))
        ):
            review_case = _case(
                session,
                organization_id,
                caller_id,
                version_id,
                title,
                created_at=NOW + timedelta(minutes=5 - index),
            )
            ordered.append(review_case)
            if visible:
                _case_member(session, organization_id, review_case.id, caller_id)
            else:
                finding = _finding(
                    session,
                    organization_id,
                    review_case.id,
                    other_id,
                    f"Hidden {title}",
                )
                _user_participant(session, organization_id, finding.id, other_id, "owner")

    actor = _actor(organization_id, department_id, caller_id)
    with Session(postgres_engine) as session:
        service = ReviewCaseCollectionQueryService(session, build_scenario_registry())
        page_one = service.list_review_cases(actor, limit=2, offset=0)
        page_two = service.list_review_cases(actor, limit=2, offset=2)

    case_a, _hidden_one, case_b, _hidden_two, case_c = ordered
    assert [item.id for item in page_one.items] == [case_a.id, case_b.id]
    assert [item.id for item in page_two.items] == [case_c.id]
    assert page_one.total == page_two.total == 3


def test_equal_created_at_uses_persisted_id_as_stable_tie_breaker(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session, session.begin():
        organization_id, department_id, caller_id, _other_id = _seed_identity(session)
        version_id = _seed_process_review_version(session, organization_id)
        # Inserted out of id order so the result order can only come from the id tie-breaker.
        low, middle, high = sorted([uuid4(), uuid4(), uuid4()], key=lambda value: value.int)
        ids = [low, high, middle]
        for index, case_id in enumerate(ids):
            review_case = _case(
                session,
                organization_id,
                caller_id,
                version_id,
                f"Same timestamp {index}",
                created_at=NOW,
                case_id=case_id,
            )
            _case_member(session, organization_id, review_case.id, caller_id)

    actor = _actor(organization_id, department_id, caller_id)
    with Session(postgres_engine) as session:
        collection = ReviewCaseCollectionQueryService(
            session,
            build_scenario_registry(),
        ).list_review_cases(actor)

    assert [item.id for item in collection.items] == sorted(
        ids,
        key=lambda value: value.int,
        reverse=True,
    )


def test_collection_query_count_is_fixed_when_hidden_graph_grows(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session, session.begin():
        organization_id, department_id, caller_id, other_id = _seed_identity(session)
        version_id = _seed_process_review_version(session, organization_id)
        visible_ids: list[UUID] = []
        for index in range(5):
            review_case = _case(
                session,
                organization_id,
                caller_id,
                version_id,
                f"Visible {index}",
                created_at=NOW + timedelta(minutes=10 - index),
            )
            visible_ids.append(review_case.id)
            _case_member(session, organization_id, review_case.id, caller_id)

    actor = _actor(organization_id, department_id, caller_id)
    with Session(postgres_engine) as session:
        small = ReviewCaseCollectionQueryService(
            session,
            build_scenario_registry(),
        ).list_review_cases(actor)
    small_count = _count_collection_selects(postgres_engine, actor)

    with Session(postgres_engine) as session, session.begin():
        for index in range(95):
            hidden_case = _case(
                session,
                organization_id,
                caller_id,
                version_id,
                f"Hidden scale {index}",
                created_at=NOW - timedelta(minutes=index + 1),
            )
            hidden_finding = _finding(
                session,
                organization_id,
                hidden_case.id,
                other_id,
                f"Hidden finding {index}",
            )
            _user_participant(
                session,
                organization_id,
                hidden_finding.id,
                other_id,
                "owner",
            )

    with Session(postgres_engine) as session:
        large = ReviewCaseCollectionQueryService(
            session,
            build_scenario_registry(),
        ).list_review_cases(actor)
    large_count = _count_collection_selects(postgres_engine, actor)

    assert [item.id for item in small.items] == visible_ids
    assert [item.id for item in large.items] == visible_ids
    assert small.total == large.total == 5
    assert small_count <= SELECT_QUERY_BOUND
    assert large_count <= SELECT_QUERY_BOUND
    assert large_count == small_count
