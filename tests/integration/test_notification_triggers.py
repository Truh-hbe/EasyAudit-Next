import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from easyaudit_next.composition import (
    build_finding_lifecycle_service,
    build_notification_orchestrator,
    build_rectification_service,
    build_review_planning_service,
)
from easyaudit_next.notifications.models import NotificationKind
from easyaudit_next.platform.persistence.models import UserRecord
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.domain.models import (
    AssignmentRole,
    DepartmentActor,
    FindingSeverity,
    ScenarioKey,
    ScenarioVersion,
    UserActor,
)
from tests.integration.notification_test_support import (
    NOW,
    notification_recipients_for_origin,
    seed_process_review_users,
)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def test_required_triggers_persist_exact_activity_and_department_t0_snapshot(
    postgres_engine: Engine,
) -> None:
    organization_id, department_id, ids = seed_process_review_users(postgres_engine)

    with Session(postgres_engine, expire_on_commit=False) as session:
        users = SqlAlchemyUserRepository(session)
        lead = users.get(ids["lead"])
        owner = users.get(ids["owner"])
        reviewer = users.get(ids["reviewer"])
        action_assignee = users.get(ids["action_assignee"])
        assert lead is not None
        assert owner is not None
        assert reviewer is not None
        assert action_assignee is not None

        planning = build_review_planning_service(session)
        orchestrator = build_notification_orchestrator(session)
        review_case = planning.create_case(
            lead,
            ScenarioKey("process_review"),
            ScenarioVersion(1),
            "M3.2 trigger catalog",
            {"area_code": "ASSY", "review_type": "routine"},
            occurred_at=NOW,
        )
        case_member_result = planning.add_case_member_result(
            lead,
            review_case.id,
            reviewer.id,
            "reviewer",
            occurred_at=NOW,
        )
        orchestrator.case_member_added(case_member_result)
        review_case = planning.transition_case(
            lead,
            review_case.id,
            "schedule",
            occurred_at=NOW,
        )
        review_case = planning.transition_case(
            lead,
            review_case.id,
            "start",
            occurred_at=NOW,
        )

        findings = build_finding_lifecycle_service(session)
        finding = findings.create_finding(
            lead,
            review_case.id,
            "Notification trigger finding",
            FindingSeverity.HIGH,
            {"issue_type": "control_gap", "project_category": "assembly"},
            occurred_at=NOW,
        )
        owner_result = findings.add_participant_result(
            lead,
            finding.id,
            UserActor(owner.id),
            "owner",
            occurred_at=NOW,
        )
        orchestrator.finding_participant_added(owner_result)
        department_result = findings.add_participant_result(
            lead,
            finding.id,
            DepartmentActor(department_id),
            "responsible_department",
            occurred_at=NOW,
        )
        orchestrator.finding_participant_added(department_result)
        finding = findings.transition_finding(
            lead,
            finding.id,
            "issue",
            occurred_at=NOW,
        )

        rectification = build_rectification_service(session)
        action_item = rectification.create_action_item(
            owner,
            finding.id,
            "Close notification action",
            occurred_at=NOW,
        )
        assignee_result = rectification.add_assignee_result(
            owner,
            action_item.id,
            UserActor(action_assignee.id),
            AssignmentRole.PRIMARY,
            occurred_at=NOW,
        )
        orchestrator.action_assignee_added(assignee_result)
        action_item = rectification.transition_action_item(
            action_assignee,
            action_item.id,
            "start",
            occurred_at=NOW,
        )
        action_item = rectification.transition_action_item(
            action_assignee,
            action_item.id,
            "complete",
            occurred_at=NOW,
        )
        assert action_item.completed_at is not None

        submission_result = rectification.submit_rectification_result(
            owner,
            finding.id,
            "submit_for_verification",
            {"stage": "completion", "comment": "Ready for verification"},
            occurred_at=NOW,
        )
        orchestrator.rectification_submitted(submission_result)
        session.commit()

    with Session(postgres_engine) as verification:
        assert notification_recipients_for_origin(
            verification,
            organization_id,
            case_member_result.activity_id,
            NotificationKind.CASE_MEMBERSHIP_ADDED,
        ) == {ids["reviewer"]}
        assert notification_recipients_for_origin(
            verification,
            organization_id,
            owner_result.activity_id,
            NotificationKind.FINDING_PARTICIPANT_ADDED,
        ) == {ids["owner"]}
        assert notification_recipients_for_origin(
            verification,
            organization_id,
            department_result.activity_id,
            NotificationKind.FINDING_PARTICIPANT_ADDED,
        ) == {ids["department_member"]}
        assert notification_recipients_for_origin(
            verification,
            organization_id,
            assignee_result.activity_id,
            NotificationKind.ACTION_ASSIGNEE_ADDED,
        ) == {ids["action_assignee"]}
        assert notification_recipients_for_origin(
            verification,
            organization_id,
            submission_result.activity_id,
            NotificationKind.FINDING_SUBMITTED_FOR_VERIFICATION,
        ) == {ids["reviewer"]}

        verification_recipients = notification_recipients_for_origin(
            verification,
            organization_id,
            submission_result.activity_id,
            NotificationKind.FINDING_SUBMITTED_FOR_VERIFICATION,
        )
        assert ids["unrelated"] not in verification_recipients
        assert ids["system_admin"] not in verification_recipients

    with Session(postgres_engine) as session, session.begin():
        persisted_member = session.get(UserRecord, ids["department_member"])
        late_member = session.get(UserRecord, ids["late_department_member"])
        assert persisted_member is not None
        assert late_member is not None
        persisted_member.primary_department_id = None
        late_member.primary_department_id = department_id

    with Session(postgres_engine) as verification:
        assert notification_recipients_for_origin(
            verification,
            organization_id,
            department_result.activity_id,
            NotificationKind.FINDING_PARTICIPANT_ADDED,
        ) == {ids["department_member"]}
