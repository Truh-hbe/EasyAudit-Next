import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, delete, inspect, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.persistence.models import (
    DepartmentRecord,
    OrganizationRecord,
    UserRecord,
)
from easyaudit_next.review_core.domain.ids import (
    ActionItemId,
    ActivityId,
    FindingId,
    ReviewCaseId,
    ReviewPlanId,
    SubmissionId,
)
from easyaudit_next.review_core.domain.models import (
    ActionAssignee,
    ActionItem,
    ActionItemActivitySubject,
    ActionItemLifecycle,
    Activity,
    AssignmentRole,
    CaseMember,
    DepartmentActor,
    Finding,
    FindingLifecycle,
    FindingParticipant,
    FindingSeverity,
    ReviewCase,
    ReviewCaseLifecycle,
    ReviewPlan,
    ScenarioKey,
    ScenarioVersion,
    Submission,
    SubmissionPurpose,
    UserActor,
)
from easyaudit_next.review_core.persistence.models import (
    ActionAssigneeRecord,
    ActionItemRecord,
    ActivityRecord,
    CaseMemberRecord,
    FindingParticipantRecord,
    FindingRecord,
    ReviewCaseRecord,
    ReviewPlanRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
    SubmissionRecord,
)
from easyaudit_next.review_core.persistence.repositories import SqlAlchemyReviewCoreRepository

NOW = datetime(2026, 8, 21, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def session(postgres_engine: Engine) -> Iterator[Session]:
    connection = postgres_engine.connect()
    transaction = connection.begin()
    database_session = Session(bind=connection, expire_on_commit=False)
    try:
        yield database_session
    finally:
        database_session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@dataclass(frozen=True)
class GraphIds:
    organization_a: UUID
    organization_b: UUID
    user_a: UUID
    user_b: UUID
    department_a: UUID
    department_b: UUID
    scenario_version_a: UUID
    case_a: UUID
    case_a_second: UUID
    finding_a: UUID
    action_a: UUID
    submission_a: UUID


def seed_graph(session: Session) -> GraphIds:
    organization_a = uuid4()
    organization_b = uuid4()
    user_a = uuid4()
    user_b = uuid4()
    department_a = uuid4()
    department_b = uuid4()
    scenario_a = uuid4()
    scenario_version_a = uuid4()
    plan_a = uuid4()
    case_a = uuid4()
    case_a_second = uuid4()
    finding_a = uuid4()
    action_a = uuid4()
    submission_a = uuid4()
    session.add_all(
        [
            OrganizationRecord(id=organization_a, name="Review Core Organization A"),
            OrganizationRecord(id=organization_b, name="Review Core Organization B"),
        ]
    )
    session.flush()
    session.add_all(
        [
            DepartmentRecord(
                id=department_a,
                organization_id=organization_a,
                name="Department A",
            ),
            DepartmentRecord(
                id=department_b,
                organization_id=organization_b,
                name="Department B",
            ),
            UserRecord(
                id=user_a,
                organization_id=organization_a,
                display_name="User A",
                platform_role="ordinary_user",
            ),
            UserRecord(
                id=user_b,
                organization_id=organization_b,
                display_name="User B",
                platform_role="ordinary_user",
            ),
        ]
    )
    session.flush()
    session.add(
        ScenarioRecord(
            id=scenario_a,
            organization_id=organization_a,
            key="process_review",
            name="Process Review",
        )
    )
    session.flush()
    session.add(
        ScenarioVersionRecord(
            id=scenario_version_a,
            scenario_id=scenario_a,
            organization_id=organization_a,
            version=1,
            published_at=NOW,
        )
    )
    session.flush()
    session.add(
        ReviewPlanRecord(
            id=plan_a,
            organization_id=organization_a,
            title="Review Plan",
            created_by=user_a,
        )
    )
    session.flush()
    session.add_all(
        [
            ReviewCaseRecord(
                id=case_a,
                organization_id=organization_a,
                plan_id=plan_a,
                scenario_version_id=scenario_version_a,
                title="Review Case A",
                lifecycle="draft",
                created_by=user_a,
                created_at=NOW,
            ),
            ReviewCaseRecord(
                id=case_a_second,
                organization_id=organization_a,
                plan_id=plan_a,
                scenario_version_id=scenario_version_a,
                title="Review Case A2",
                lifecycle="draft",
                created_by=user_a,
                created_at=NOW,
            ),
        ]
    )
    session.flush()
    session.add(
        FindingRecord(
            id=finding_a,
            organization_id=organization_a,
            case_id=case_a,
            title="Finding A",
            severity="high",
            lifecycle="open",
            raised_by=user_a,
            raised_at=NOW,
        )
    )
    session.flush()
    session.add(
        ActionItemRecord(
            id=action_a,
            organization_id=organization_a,
            finding_id=finding_a,
            title="Action A",
            lifecycle="todo",
        )
    )
    session.flush()
    session.add(
        SubmissionRecord(
            id=submission_a,
            organization_id=organization_a,
            case_id=case_a,
            finding_id=finding_a,
            purpose="rectification",
            submitted_by=user_a,
            submitted_at=NOW,
            payload_json={"note": "submitted"},
        )
    )
    session.flush()
    return GraphIds(
        organization_a=organization_a,
        organization_b=organization_b,
        user_a=user_a,
        user_b=user_b,
        department_a=department_a,
        department_b=department_b,
        scenario_version_a=scenario_version_a,
        case_a=case_a,
        case_a_second=case_a_second,
        finding_a=finding_a,
        action_a=action_a,
        submission_a=submission_a,
    )


def test_migration_creates_review_core_tables(postgres_engine: Engine) -> None:
    expected = {
        "review_plans",
        "review_cases",
        "case_members",
        "findings",
        "finding_participants",
        "action_items",
        "action_assignees",
        "submissions",
        "activities",
    }
    assert expected <= set(inspect(postgres_engine).get_table_names())


def test_repository_round_trips_core_entities_and_typed_actors(session: Session) -> None:
    ids = seed_graph(session)
    repository = SqlAlchemyReviewCoreRepository(session)
    organization_id = OrganizationId(ids.organization_a)
    user_id = UserId(ids.user_a)
    department_id = DepartmentId(ids.department_a)
    plan = ReviewPlan(
        id=ReviewPlanId(uuid4()),
        organization_id=organization_id,
        title="Repository Plan",
        planned_start_at=None,
        planned_end_at=None,
        created_by=user_id,
    )
    review_case = ReviewCase(
        id=ReviewCaseId(uuid4()),
        organization_id=organization_id,
        plan_id=plan.id,
        scenario_key=ScenarioKey("process_review"),
        scenario_version=ScenarioVersion(1),
        title="Repository Case",
        lifecycle=ReviewCaseLifecycle.DRAFT,
        created_by=user_id,
        created_at=NOW,
    )
    finding = Finding(
        id=FindingId(uuid4()),
        organization_id=organization_id,
        case_id=review_case.id,
        title="Repository Finding",
        description="Strong FK round trip",
        severity=FindingSeverity.HIGH,
        lifecycle=FindingLifecycle.OPEN,
        raised_by=user_id,
        raised_at=NOW,
    )
    action = ActionItem(
        id=ActionItemId(uuid4()),
        organization_id=organization_id,
        finding_id=finding.id,
        title="Repository Action",
        lifecycle=ActionItemLifecycle.TODO,
        due_at=None,
    )
    submission = Submission(
        id=SubmissionId(uuid4()),
        organization_id=organization_id,
        case_id=review_case.id,
        finding_id=finding.id,
        purpose=SubmissionPurpose.RECTIFICATION,
        submitted_by=user_id,
        submitted_at=NOW,
        payload={"evidence": "snapshot"},
    )
    activity = Activity(
        id=ActivityId(uuid4()),
        organization_id=organization_id,
        subject=ActionItemActivitySubject(action.id),
        event_type="action.created",
        actor_id=user_id,
        occurred_at=NOW,
        metadata={"source": "repository-test"},
    )

    repository.add_plan(plan)
    repository.add_case(review_case)
    repository.add_case_member(CaseMember(organization_id, review_case.id, user_id, "lead", NOW))
    repository.add_finding(finding)
    repository.add_finding_participant(
        FindingParticipant(
            organization_id,
            finding.id,
            UserActor(user_id),
            "owner",
            NOW,
        )
    )
    repository.add_finding_participant(
        FindingParticipant(
            organization_id,
            finding.id,
            DepartmentActor(department_id),
            "responsible_department",
            NOW,
        )
    )
    repository.add_action_item(action)
    repository.add_action_assignee(
        ActionAssignee(
            organization_id,
            action.id,
            UserActor(user_id),
            AssignmentRole.PRIMARY,
            NOW,
        )
    )
    repository.add_action_assignee(
        ActionAssignee(
            organization_id,
            action.id,
            DepartmentActor(department_id),
            AssignmentRole.COLLABORATOR,
            NOW,
        )
    )
    repository.add_submission(submission)
    repository.add_activity(activity)

    assert repository.get_plan(organization_id, plan.id) == plan
    assert repository.get_case(organization_id, review_case.id) == review_case
    assert repository.get_finding(organization_id, finding.id) == finding
    assert repository.get_action_item(organization_id, action.id) == action
    assert repository.get_submission(organization_id, submission.id) == submission
    assert repository.get_activity(organization_id, activity.id) == activity


def test_database_rejects_cross_organization_case_member(session: Session) -> None:
    ids = seed_graph(session)
    session.add(
        CaseMemberRecord(
            organization_id=ids.organization_a,
            case_id=ids.case_a,
            user_id=ids.user_b,
            role_key="observer",
            joined_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize("actor_type", ["user", "department"])
def test_database_rejects_cross_organization_finding_actor(
    session: Session, actor_type: str
) -> None:
    ids = seed_graph(session)
    session.add(
        FindingParticipantRecord(
            id=uuid4(),
            organization_id=ids.organization_a,
            finding_id=ids.finding_a,
            user_id=ids.user_b if actor_type == "user" else None,
            department_id=ids.department_b if actor_type == "department" else None,
            role_key="owner",
            assigned_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize("actor_type", ["user", "department"])
def test_database_rejects_cross_organization_action_actor(
    session: Session, actor_type: str
) -> None:
    ids = seed_graph(session)
    session.add(
        ActionAssigneeRecord(
            id=uuid4(),
            organization_id=ids.organization_a,
            action_item_id=ids.action_a,
            user_id=ids.user_b if actor_type == "user" else None,
            department_id=ids.department_b if actor_type == "department" else None,
            role="primary",
            assigned_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize("actor_count", [0, 2])
def test_finding_participant_requires_exactly_one_actor(session: Session, actor_count: int) -> None:
    ids = seed_graph(session)
    session.add(
        FindingParticipantRecord(
            id=uuid4(),
            organization_id=ids.organization_a,
            finding_id=ids.finding_a,
            user_id=ids.user_a if actor_count == 2 else None,
            department_id=ids.department_a if actor_count == 2 else None,
            role_key="owner",
            assigned_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize("actor_count", [0, 2])
def test_action_assignee_requires_exactly_one_actor(session: Session, actor_count: int) -> None:
    ids = seed_graph(session)
    session.add(
        ActionAssigneeRecord(
            id=uuid4(),
            organization_id=ids.organization_a,
            action_item_id=ids.action_a,
            user_id=ids.user_a if actor_count == 2 else None,
            department_id=ids.department_a if actor_count == 2 else None,
            role="primary",
            assigned_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_submission_finding_must_belong_to_same_case(session: Session) -> None:
    ids = seed_graph(session)
    session.add(
        SubmissionRecord(
            id=uuid4(),
            organization_id=ids.organization_a,
            case_id=ids.case_a_second,
            finding_id=ids.finding_a,
            purpose="rectification",
            submitted_by=ids.user_a,
            submitted_at=NOW,
            payload_json={},
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize("target_count", [0, 2])
def test_activity_requires_exactly_one_typed_target(session: Session, target_count: int) -> None:
    ids = seed_graph(session)
    session.add(
        ActivityRecord(
            id=uuid4(),
            organization_id=ids.organization_a,
            actor_id=ids.user_a,
            event_type="invalid.activity",
            occurred_at=NOW,
            review_case_id=ids.case_a if target_count == 2 else None,
            finding_id=ids.finding_a if target_count == 2 else None,
            metadata_json={},
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_activity_rejects_cross_organization_actor(session: Session) -> None:
    ids = seed_graph(session)
    session.add(
        ActivityRecord(
            id=uuid4(),
            organization_id=ids.organization_a,
            actor_id=ids.user_b,
            event_type="finding.issued",
            occurred_at=NOW,
            finding_id=ids.finding_a,
            metadata_json={},
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_activity_rejects_dangling_typed_target(session: Session) -> None:
    ids = seed_graph(session)
    session.add(
        ActivityRecord(
            id=uuid4(),
            organization_id=ids.organization_a,
            actor_id=ids.user_a,
            event_type="finding.issued",
            occurred_at=NOW,
            finding_id=uuid4(),
            metadata_json={},
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize("statement", ["update", "delete"])
def test_activities_are_append_only(session: Session, statement: str) -> None:
    ids = seed_graph(session)
    activity_id = uuid4()
    session.add(
        ActivityRecord(
            id=activity_id,
            organization_id=ids.organization_a,
            actor_id=ids.user_a,
            event_type="finding.issued",
            occurred_at=NOW,
            finding_id=ids.finding_a,
            metadata_json={"immutable": True},
        )
    )
    session.flush()
    command = (
        update(ActivityRecord).where(ActivityRecord.id == activity_id).values(event_type="tampered")
        if statement == "update"
        else delete(ActivityRecord).where(ActivityRecord.id == activity_id)
    )
    with pytest.raises(DBAPIError):
        session.execute(command)
