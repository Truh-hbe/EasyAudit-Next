import os
from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from easyaudit_next.collaboration.notification_orchestration import NotificationOrchestrator
from easyaudit_next.composition import (
    build_finding_lifecycle_service,
    build_rectification_service,
    build_review_planning_service,
    build_scenario_registry,
)
from easyaudit_next.notifications.models import NotificationDraft
from easyaudit_next.notifications.persistence import (
    NotificationRecord,
    SqlAlchemyNotificationRepository,
)
from easyaudit_next.notifications.service import NotificationService
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.domain.ids import ActivityId
from easyaudit_next.review_core.domain.models import (
    AssignmentRole,
    DepartmentActor,
    FindingSeverity,
    ScenarioKey,
    ScenarioVersion,
    UserActor,
)
from easyaudit_next.review_core.persistence.models import (
    ActionAssigneeRecord,
    ActivityRecord,
    CaseMemberRecord,
    FindingParticipantRecord,
    FindingRecord,
    SubmissionRecord,
)
from tests.integration.notification_test_support import (
    NOW,
    seed_process_review_users,
)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


class _RejectNotificationRepository(SqlAlchemyNotificationRepository):
    """Fail through the real Notification title CHECK after the Review mutation flushes."""

    def add_many(self, drafts: tuple[NotificationDraft, ...]) -> None:
        if not drafts:
            return
        draft = drafts[0]
        subject_columns = self._subject_columns(draft.subject)
        self._session.add(
            NotificationRecord(
                id=draft.id,
                organization_id=draft.organization_id,
                recipient_user_id=draft.recipient_user_id,
                kind=draft.kind.value,
                origin_activity_id=draft.origin_activity_id,
                title="",
                body=draft.body,
                created_at=draft.created_at,
                **subject_columns,
            )
        )
        self._session.flush()


def _failing_orchestrator(session: Session) -> NotificationOrchestrator:
    return NotificationOrchestrator(
        session,
        build_scenario_registry(),
        NotificationService(_RejectNotificationRepository(session)),
    )


def _activity_absent(session: Session, activity_id: ActivityId | None) -> bool:
    assert activity_id is not None
    return session.get(ActivityRecord, activity_id) is None


def test_notification_failure_rolls_back_all_four_trigger_mutations(
    postgres_engine: Engine,
) -> None:
    organization_id, department_id, ids = seed_process_review_users(postgres_engine)

    with Session(postgres_engine, expire_on_commit=False) as session:
        lead = SqlAlchemyUserRepository(session).get(ids["lead"])
        assert lead is not None
        review_case = build_review_planning_service(session).create_case(
            lead,
            ScenarioKey("process_review"),
            ScenarioVersion(1),
            "Notification atomicity",
            {"area_code": "ASSY", "review_type": "routine"},
            occurred_at=NOW,
        )
        case_id = review_case.id
        session.commit()

    failed_case_activity: ActivityId | None = None
    with pytest.raises(IntegrityError):
        with Session(postgres_engine) as session, session.begin():
            lead = SqlAlchemyUserRepository(session).get(ids["lead"])
            assert lead is not None
            result = build_review_planning_service(session).add_case_member_result(
                lead,
                case_id,
                ids["reviewer"],
                "reviewer",
                occurred_at=NOW,
            )
            failed_case_activity = result.activity_id
            _failing_orchestrator(session).case_member_added(result)

    with Session(postgres_engine) as verification:
        member = verification.scalar(
            select(CaseMemberRecord).where(
                CaseMemberRecord.organization_id == organization_id,
                CaseMemberRecord.case_id == case_id,
                CaseMemberRecord.user_id == ids["reviewer"],
                CaseMemberRecord.role_key == "reviewer",
            )
        )
        assert member is None
        assert _activity_absent(verification, failed_case_activity)

    with Session(postgres_engine) as session, session.begin():
        lead = SqlAlchemyUserRepository(session).get(ids["lead"])
        assert lead is not None
        planning = build_review_planning_service(session)
        planning.add_case_member(
            lead,
            case_id,
            ids["reviewer"],
            "reviewer",
            occurred_at=NOW,
        )
        planning.transition_case(lead, case_id, "schedule", occurred_at=NOW)
        planning.transition_case(lead, case_id, "start", occurred_at=NOW)

    with Session(postgres_engine, expire_on_commit=False) as session:
        lead = SqlAlchemyUserRepository(session).get(ids["lead"])
        assert lead is not None
        finding = build_finding_lifecycle_service(session).create_finding(
            lead,
            case_id,
            "Atomicity finding",
            FindingSeverity.HIGH,
            {"issue_type": "control_gap", "project_category": "assembly"},
            occurred_at=NOW,
        )
        finding_id = finding.id
        session.commit()

    failed_participant_activity: ActivityId | None = None
    with pytest.raises(IntegrityError):
        with Session(postgres_engine) as session, session.begin():
            lead = SqlAlchemyUserRepository(session).get(ids["lead"])
            assert lead is not None
            result = build_finding_lifecycle_service(session).add_participant_result(
                lead,
                finding_id,
                UserActor(ids["owner"]),
                "owner",
                occurred_at=NOW,
            )
            failed_participant_activity = result.activity_id
            _failing_orchestrator(session).finding_participant_added(result)

    with Session(postgres_engine) as verification:
        participant = verification.scalar(
            select(FindingParticipantRecord).where(
                FindingParticipantRecord.organization_id == organization_id,
                FindingParticipantRecord.finding_id == finding_id,
                FindingParticipantRecord.user_id == ids["owner"],
                FindingParticipantRecord.role_key == "owner",
            )
        )
        assert participant is None
        assert _activity_absent(verification, failed_participant_activity)

    with Session(postgres_engine) as session, session.begin():
        lead = SqlAlchemyUserRepository(session).get(ids["lead"])
        assert lead is not None
        findings = build_finding_lifecycle_service(session)
        findings.add_participant(
            lead,
            finding_id,
            UserActor(ids["owner"]),
            "owner",
            occurred_at=NOW,
        )
        findings.add_participant(
            lead,
            finding_id,
            DepartmentActor(department_id),
            "responsible_department",
            occurred_at=NOW,
        )
        findings.transition_finding(lead, finding_id, "issue", occurred_at=NOW)

    with Session(postgres_engine, expire_on_commit=False) as session:
        owner = SqlAlchemyUserRepository(session).get(ids["owner"])
        assert owner is not None
        action_item = build_rectification_service(session).create_action_item(
            owner,
            finding_id,
            "Atomicity action",
            occurred_at=NOW,
        )
        action_id = action_item.id
        session.commit()

    failed_assignee_activity: ActivityId | None = None
    with pytest.raises(IntegrityError):
        with Session(postgres_engine) as session, session.begin():
            owner = SqlAlchemyUserRepository(session).get(ids["owner"])
            assert owner is not None
            result = build_rectification_service(session).add_assignee_result(
                owner,
                action_id,
                UserActor(ids["action_assignee"]),
                AssignmentRole.PRIMARY,
                occurred_at=NOW,
            )
            failed_assignee_activity = result.activity_id
            _failing_orchestrator(session).action_assignee_added(result)

    with Session(postgres_engine) as verification:
        assignee = verification.scalar(
            select(ActionAssigneeRecord).where(
                ActionAssigneeRecord.organization_id == organization_id,
                ActionAssigneeRecord.action_item_id == action_id,
                ActionAssigneeRecord.user_id == ids["action_assignee"],
                ActionAssigneeRecord.role == AssignmentRole.PRIMARY.value,
            )
        )
        assert assignee is None
        assert _activity_absent(verification, failed_assignee_activity)

    with Session(postgres_engine) as session, session.begin():
        owner = SqlAlchemyUserRepository(session).get(ids["owner"])
        action_assignee = SqlAlchemyUserRepository(session).get(ids["action_assignee"])
        assert owner is not None
        assert action_assignee is not None
        rectification = build_rectification_service(session)
        rectification.add_assignee(
            owner,
            action_id,
            UserActor(ids["action_assignee"]),
            AssignmentRole.PRIMARY,
            occurred_at=NOW,
        )
        rectification.transition_action_item(
            action_assignee,
            action_id,
            "start",
            occurred_at=NOW,
        )
        rectification.transition_action_item(
            action_assignee,
            action_id,
            "complete",
            occurred_at=NOW,
        )

    failed_submission_activity: ActivityId | None = None
    failed_submission_id: UUID | None = None
    with pytest.raises(IntegrityError):
        with Session(postgres_engine) as session, session.begin():
            owner = SqlAlchemyUserRepository(session).get(ids["owner"])
            assert owner is not None
            result = build_rectification_service(session).submit_rectification_result(
                owner,
                finding_id,
                "submit_for_verification",
                {"stage": "completion", "comment": "Ready"},
                occurred_at=NOW,
            )
            failed_submission_activity = result.activity_id
            failed_submission_id = result.submission.id
            _failing_orchestrator(session).rectification_submitted(result)

    with Session(postgres_engine) as verification:
        finding_record = verification.get(FindingRecord, finding_id)
        assert finding_record is not None
        assert finding_record.lifecycle == "rectifying"
        assert failed_submission_id is not None
        assert verification.get(SubmissionRecord, failed_submission_id) is None
        assert _activity_absent(verification, failed_submission_activity)

        failed_activity_ids = {
            failed_case_activity,
            failed_participant_activity,
            failed_assignee_activity,
            failed_submission_activity,
        }
        notification_count = verification.scalar(
            select(NotificationRecord.id).where(
                NotificationRecord.origin_activity_id.in_(failed_activity_ids)
            )
        )
        assert notification_count is None
