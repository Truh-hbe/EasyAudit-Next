import os
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from easyaudit_next.composition import (
    build_finding_lifecycle_service,
    build_notification_orchestrator,
    build_notification_service,
    build_notification_subject_context_resolver,
    build_rectification_service,
    build_review_planning_service,
)
from easyaudit_next.notifications.models import (
    ActionItemNotificationSubject,
    FindingNotificationSubject,
    NotificationItem,
    NotificationKind,
    ReviewCaseNotificationSubject,
)
from easyaudit_next.notifications.subject_context import NotificationSubjectContext
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.domain.models import User
from easyaudit_next.platform.persistence.models import UserRecord
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.application.mutation_results import ActionAssigneeAddedResult
from easyaudit_next.review_core.domain.ids import ActionItemId
from easyaudit_next.review_core.domain.models import (
    AssignmentRole,
    DepartmentActor,
    FindingSeverity,
    ScenarioKey,
    ScenarioVersion,
    UserActor,
)
from tests.integration.notification_test_support import NOW, seed_process_review_users

CASE_TITLE = "Confidential Case Alpha"
FINDING_TITLE = "Confidential Finding Beta"
ACTION_TITLE = "Confidential Action Gamma"


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


@dataclass(frozen=True)
class Seeded:
    organization_id: OrganizationId
    ids: dict[str, UserId]
    case_id: UUID
    finding_id: UUID
    action_id: UUID


def _build_case(
    session: Session,
    ids: dict[str, UserId],
    department_id: UUID,
    *,
    title: str = CASE_TITLE,
    member_key: str = "reviewer",
    extra_actions: int = 0,
    assignee_key: str = "action_assignee",
) -> tuple[UUID, UUID, UUID]:
    users = SqlAlchemyUserRepository(session)
    lead = users.get(ids["lead"])
    owner = users.get(ids["owner"])
    assert lead is not None and owner is not None

    planning = build_review_planning_service(session)
    orchestrator = build_notification_orchestrator(session)
    review_case = planning.create_case(
        lead,
        ScenarioKey("process_review"),
        ScenarioVersion(1),
        title,
        {"area_code": "ASSY", "review_type": "routine"},
        occurred_at=NOW,
    )
    orchestrator.case_member_added(
        planning.add_case_member_result(
            lead, review_case.id, ids[member_key], "reviewer", occurred_at=NOW
        )
    )
    planning.transition_case(lead, review_case.id, "schedule", occurred_at=NOW)
    planning.transition_case(lead, review_case.id, "start", occurred_at=NOW)

    findings = build_finding_lifecycle_service(session)
    finding = findings.create_finding(
        lead,
        review_case.id,
        FINDING_TITLE,
        FindingSeverity.HIGH,
        {"issue_type": "control_gap", "project_category": "assembly"},
        occurred_at=NOW,
    )
    orchestrator.finding_participant_added(
        findings.add_participant_result(
            lead, finding.id, UserActor(owner.id), "owner", occurred_at=NOW
        )
    )
    orchestrator.finding_participant_added(
        findings.add_participant_result(
            lead,
            finding.id,
            DepartmentActor(department_id),
            "responsible_department",
            occurred_at=NOW,
        )
    )
    findings.transition_finding(lead, finding.id, "issue", occurred_at=NOW)

    rectification = build_rectification_service(session)
    first_action_id: UUID | None = None
    for index in range(1 + extra_actions):
        action = rectification.create_action_item(
            owner,
            finding.id,
            ACTION_TITLE if index == 0 else f"{ACTION_TITLE} #{index}",
            occurred_at=NOW,
        )
        first_action_id = first_action_id or action.id
        orchestrator.action_assignee_added(
            rectification.add_assignee_result(
                owner,
                action.id,
                UserActor(ids[assignee_key]),
                AssignmentRole.PRIMARY if index == 0 else AssignmentRole.COLLABORATOR,
                occurred_at=NOW,
            )
        )
    assert first_action_id is not None
    return review_case.id, finding.id, first_action_id


def _seed(engine: Engine, *, extra_actions: int = 0) -> Seeded:
    organization_id, department_id, ids = seed_process_review_users(engine)
    with Session(engine, expire_on_commit=False) as session:
        case_id, finding_id, action_id = _build_case(
            session, ids, department_id, extra_actions=extra_actions
        )
        session.commit()
    return Seeded(organization_id, ids, case_id, finding_id, action_id)


def _inbox(
    engine: Engine,
    seeded: Seeded,
    user_key: str,
) -> tuple[tuple[NotificationItem, ...], dict[object, NotificationSubjectContext]]:
    with Session(engine) as session:
        user = SqlAlchemyUserRepository(session).get(seeded.ids[user_key])
        assert user is not None
        page = build_notification_service(session).get_inbox(
            seeded.organization_id, user.id, limit=100, offset=0
        )
        contexts = build_notification_subject_context_resolver(session).resolve(user, page.items)
        session.rollback()
    return page.items, contexts


def test_assignee_sees_the_action_and_role_but_not_parents_it_cannot_open(
    postgres_engine: Engine,
) -> None:
    seeded = _seed(postgres_engine)

    items, contexts = _inbox(postgres_engine, seeded, "action_assignee")

    (item,) = items
    assert item.kind is NotificationKind.ACTION_ASSIGNEE_ADDED
    context = contexts[item.id]
    assert context.title == ACTION_TITLE
    assert context.role_keys == ("primary",)
    # An Action-only assignee cannot open the parent Finding or Case, so neither title is shown.
    assert context.finding_title is None
    assert context.case_title is None


def test_finding_owner_sees_finding_and_case_titles(postgres_engine: Engine) -> None:
    seeded = _seed(postgres_engine)

    items, contexts = _inbox(postgres_engine, seeded, "owner")

    (item,) = items
    assert item.kind is NotificationKind.FINDING_PARTICIPANT_ADDED
    context = contexts[item.id]
    assert context.title == FINDING_TITLE
    assert context.role_keys == ("owner",)
    assert context.case_title == CASE_TITLE


def test_removed_case_member_keeps_the_notification_but_loses_the_title(
    postgres_engine: Engine,
) -> None:
    seeded = _seed(postgres_engine)
    before_items, before = _inbox(postgres_engine, seeded, "reviewer")
    (item,) = before_items
    assert before[item.id].title == CASE_TITLE
    assert before[item.id].role_keys == ("reviewer",)

    with Session(postgres_engine, expire_on_commit=False) as session:
        lead = SqlAlchemyUserRepository(session).get(seeded.ids["lead"])
        assert lead is not None
        build_review_planning_service(session).remove_case_member(
            lead, seeded.case_id, seeded.ids["reviewer"], "reviewer", occurred_at=NOW
        )
        session.commit()

    after_items, after = _inbox(postgres_engine, seeded, "reviewer")

    assert [after_item.id for after_item in after_items] == [item.id]
    assert after == {}


def test_new_executor_after_transfer_and_reopen_sees_the_action(
    postgres_engine: Engine,
) -> None:
    seeded = _seed(postgres_engine)
    with Session(postgres_engine, expire_on_commit=False) as session:
        users = SqlAlchemyUserRepository(session)
        owner = users.get(seeded.ids["owner"])
        assignee = users.get(seeded.ids["action_assignee"])
        assert owner is not None and assignee is not None
        rectification = build_rectification_service(session)
        action_id = ActionItemId(seeded.action_id)
        rectification.transition_action_item(assignee, action_id, "start", occurred_at=NOW)
        rectification.transition_action_item(assignee, action_id, "complete", occurred_at=NOW)
        session.commit()
    with Session(postgres_engine) as session, session.begin():
        record = session.get(UserRecord, seeded.ids["action_assignee"])
        assert record is not None
        record.is_active = False
    with Session(postgres_engine, expire_on_commit=False) as session:
        owner = SqlAlchemyUserRepository(session).get(seeded.ids["owner"])
        assert owner is not None
        result = build_rectification_service(session).transfer_and_reopen_action(
            owner,
            ActionItemId(seeded.action_id),
            seeded.ids["unrelated"],
            "Original executor left the company",
            occurred_at=NOW,
        )
        build_notification_orchestrator(session).action_assignee_added(
            ActionAssigneeAddedResult(assignee=result.new_assignee, activity_id=result.activity_id)
        )
        session.commit()

    items, contexts = _inbox(postgres_engine, seeded, "unrelated")

    (item,) = items
    assert item.kind is NotificationKind.ACTION_ASSIGNEE_ADDED
    assert contexts[item.id].title == ACTION_TITLE
    assert contexts[item.id].role_keys == ("primary",)
    assert contexts[item.id].finding_title is None  # new executor holds only the Action grant


def test_recipient_from_another_organization_never_resolves_foreign_targets(
    postgres_engine: Engine,
) -> None:
    seeded = _seed(postgres_engine)
    other = _seed(postgres_engine)
    items, _ = _inbox(postgres_engine, seeded, "action_assignee")
    assert items

    with Session(postgres_engine) as session:
        outsider = SqlAlchemyUserRepository(session).get(other.ids["action_assignee"])
        assert isinstance(outsider, User)
        contexts = build_notification_subject_context_resolver(session).resolve(outsider, items)
        session.rollback()

    assert contexts == {}


def _mixed_org(engine: Engine, case_count: int) -> Seeded:
    """One recipient (owner) with a Case, a Finding and an Action notification in each Case."""
    organization_id, department_id, ids = seed_process_review_users(engine)
    with Session(engine, expire_on_commit=False) as session:
        built = [
            _build_case(
                session,
                ids,
                department_id,
                title=f"{CASE_TITLE} {index}",
                member_key="owner",
                assignee_key="owner",
            )
            for index in range(case_count)
        ]
        session.commit()
    return Seeded(organization_id, ids, built[0][0], built[0][1], built[0][2])


def _select_count(engine: Engine, seeded: Seeded, user_key: str) -> tuple[int, list[object]]:
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

    with Session(engine) as session:
        user = SqlAlchemyUserRepository(session).get(seeded.ids[user_key])
        assert user is not None
        page = build_notification_service(session).get_inbox(
            seeded.organization_id, user.id, limit=100, offset=0
        )
        resolver = build_notification_subject_context_resolver(session)
        event.listen(engine, "before_cursor_execute", before_cursor_execute)
        try:
            contexts = resolver.resolve(user, page.items)
        finally:
            event.remove(engine, "before_cursor_execute", before_cursor_execute)
        session.rollback()
    assert len(contexts) == len(page.items)
    return count, [item.subject for item in page.items]


def test_resolution_uses_a_fixed_number_of_selects_per_page(postgres_engine: Engine) -> None:
    # Same-kind page: 2 vs 15 Action notifications.
    small = _seed(postgres_engine, extra_actions=1)
    large = _seed(postgres_engine, extra_actions=14)
    small_selects, small_subjects = _select_count(postgres_engine, small, "action_assignee")
    large_selects, large_subjects = _select_count(postgres_engine, large, "action_assignee")
    assert (len(small_subjects), len(large_subjects)) == (2, 15)
    assert large_selects == small_selects

    # Mixed page: Case + Finding + Action subjects across several Cases.
    one_case = _select_count(postgres_engine, _mixed_org(postgres_engine, 1), "owner")
    five_cases = _select_count(postgres_engine, _mixed_org(postgres_engine, 5), "owner")
    for _, subjects in (one_case, five_cases):
        assert {type(subject) for subject in subjects} == {
            ReviewCaseNotificationSubject,
            FindingNotificationSubject,
            ActionItemNotificationSubject,
        }
    assert len(one_case[1]) == 3 and len(five_cases[1]) == 15
    assert five_cases[0] == one_case[0]
