import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from easyaudit_next.collaboration.notification_orchestration import NotificationOrchestrator
from easyaudit_next.composition import (
    build_finding_lifecycle_service,
    build_notification_orchestrator,
    build_notification_service,
    build_rectification_service,
    build_review_planning_service,
)
from easyaudit_next.notifications.models import NotificationKind
from easyaudit_next.notifications.persistence import NotificationRecord
from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.persistence.models import (
    DepartmentRecord,
    OrganizationRecord,
    UserRecord,
)
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.application.mutation_results import RectificationSubmissionResult
from easyaudit_next.review_core.domain.ids import (
    ActivityId,
    FindingId,
    ReviewCaseId,
    SubmissionId,
)
from easyaudit_next.review_core.domain.models import (
    AssignmentRole,
    DepartmentActor,
    Finding,
    FindingLifecycle,
    FindingSeverity,
    Scenario,
    ScenarioKey,
    ScenarioVersion,
    Submission,
    SubmissionPurpose,
    UserActor,
)
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActorKind,
    AuthorizationContext,
    PermissionSource,
)
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry
from easyaudit_next.review_core.persistence.models import (
    ActivityRecord,
    FindingParticipantRecord,
    FindingRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
    SubmissionRecord,
)
from easyaudit_next.scenarios.process_review import PROCESS_REVIEW_V1

NOW = datetime(2026, 8, 27, 15, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _seed_process_review_users(
    engine: Engine,
) -> tuple[OrganizationId, DepartmentId, dict[str, UserId]]:
    organization_id = OrganizationId(uuid4())
    department_id = DepartmentId(uuid4())
    users = {
        "lead": UserId(uuid4()),
        "owner": UserId(uuid4()),
        "reviewer": UserId(uuid4()),
        "action_assignee": UserId(uuid4()),
        "department_member": UserId(uuid4()),
        "inactive_department_member": UserId(uuid4()),
        "late_department_member": UserId(uuid4()),
        "observer_a": UserId(uuid4()),
        "observer_b": UserId(uuid4()),
    }
    scenario_id = uuid4()

    with Session(engine) as session, session.begin():
        session.add(
            OrganizationRecord(
                id=organization_id,
                name=f"Notification orchestration {organization_id}",
            )
        )
        session.flush()
        session.add(
            DepartmentRecord(
                id=department_id,
                organization_id=organization_id,
                name="Responsible Department",
            )
        )
        session.flush()
        for name, user_id in users.items():
            session.add(
                UserRecord(
                    id=user_id,
                    organization_id=organization_id,
                    primary_department_id=(
                        department_id
                        if name in {"department_member", "inactive_department_member"}
                        else None
                    ),
                    display_name=name.replace("_", " ").title(),
                    platform_role="ordinary_user",
                    is_active=name != "inactive_department_member",
                )
            )
        session.flush()
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
                id=uuid4(),
                scenario_id=scenario_id,
                organization_id=organization_id,
                version=1,
                published_at=NOW,
            )
        )
    return organization_id, department_id, users


def _notification_recipients_for_origin(
    session: Session,
    organization_id: OrganizationId,
    origin_activity_id: ActivityId,
    kind: NotificationKind,
) -> set[UUID]:
    return set(
        session.scalars(
            select(NotificationRecord.recipient_user_id).where(
                NotificationRecord.organization_id == organization_id,
                NotificationRecord.origin_activity_id == origin_activity_id,
                NotificationRecord.kind == kind.value,
            )
        )
    )


def test_four_required_triggers_use_exact_activity_and_department_t0_snapshot(
    postgres_engine: Engine,
) -> None:
    organization_id, department_id, ids = _seed_process_review_users(postgres_engine)

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
        assert _notification_recipients_for_origin(
            verification,
            organization_id,
            case_member_result.activity_id,
            NotificationKind.CASE_MEMBERSHIP_ADDED,
        ) == {ids["reviewer"]}
        assert _notification_recipients_for_origin(
            verification,
            organization_id,
            owner_result.activity_id,
            NotificationKind.FINDING_PARTICIPANT_ADDED,
        ) == {ids["owner"]}
        assert _notification_recipients_for_origin(
            verification,
            organization_id,
            department_result.activity_id,
            NotificationKind.FINDING_PARTICIPANT_ADDED,
        ) == {ids["department_member"]}
        assert _notification_recipients_for_origin(
            verification,
            organization_id,
            assignee_result.activity_id,
            NotificationKind.ACTION_ASSIGNEE_ADDED,
        ) == {ids["action_assignee"]}
        assert _notification_recipients_for_origin(
            verification,
            organization_id,
            submission_result.activity_id,
            NotificationKind.FINDING_SUBMITTED_FOR_VERIFICATION,
        ) == {ids["reviewer"]}

    with Session(postgres_engine) as session, session.begin():
        persisted_member = session.get(UserRecord, ids["department_member"])
        late_member = session.get(UserRecord, ids["late_department_member"])
        assert persisted_member is not None
        assert late_member is not None
        persisted_member.primary_department_id = None
        late_member.primary_department_id = department_id

    with Session(postgres_engine) as verification:
        assert _notification_recipients_for_origin(
            verification,
            organization_id,
            department_result.activity_id,
            NotificationKind.FINDING_PARTICIPANT_ADDED,
        ) == {ids["department_member"]}


def test_concurrent_same_subject_same_event_type_cannot_cross_bind_provenance(
    postgres_engine: Engine,
) -> None:
    organization_id, _, ids = _seed_process_review_users(postgres_engine)

    with Session(postgres_engine, expire_on_commit=False) as session:
        lead = SqlAlchemyUserRepository(session).get(ids["lead"])
        assert lead is not None
        review_case = build_review_planning_service(session).create_case(
            lead,
            ScenarioKey("process_review"),
            ScenarioVersion(1),
            "Concurrent provenance case",
            {"area_code": "ASSY", "review_type": "routine"},
            occurred_at=NOW,
        )
        case_id = review_case.id
        session.commit()

    barrier = Barrier(2)

    def add_observer(target_user_id: UserId) -> tuple[UserId, ActivityId]:
        with Session(postgres_engine) as session:
            lead = SqlAlchemyUserRepository(session).get(ids["lead"])
            assert lead is not None
            barrier.wait()
            result = build_review_planning_service(session).add_case_member_result(
                lead,
                case_id,
                target_user_id,
                "observer",
                occurred_at=NOW,
            )
            build_notification_orchestrator(session).case_member_added(result)
            session.commit()
            return target_user_id, result.activity_id

    targets = (ids["observer_a"], ids["observer_b"])
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [future.result(timeout=10) for future in map(executor.submit, [lambda: add_observer(targets[0]), lambda: add_observer(targets[1])])]

    expected = dict(results)
    with Session(postgres_engine) as verification:
        notifications = tuple(
            verification.scalars(
                select(NotificationRecord).where(
                    NotificationRecord.organization_id == organization_id,
                    NotificationRecord.review_case_id == case_id,
                    NotificationRecord.kind == NotificationKind.CASE_MEMBERSHIP_ADDED.value,
                    NotificationRecord.recipient_user_id.in_(targets),
                )
            )
        )
        assert len(notifications) == 2
        for notification in notifications:
            recipient_id = UserId(notification.recipient_user_id)
            assert notification.origin_activity_id == expected[recipient_id]
            activity = verification.get(ActivityRecord, notification.origin_activity_id)
            assert activity is not None
            assert activity.review_case_id == case_id
            assert activity.event_type == "review_case.member_added"
            assert activity.occurred_at == NOW
            assert activity.metadata_json["user_id"] == str(recipient_id)


class _TargetOwnerVerifies:
    def allows(self, permission: str, context: AuthorizationContext) -> bool:
        if permission != "verify_finding":
            return False
        return any(
            grant.role_key == "owner"
            and grant.actor_kind is ActorKind.USER
            and grant.source is PermissionSource.DIRECT
            for grant in context.finding_role_grants
        )


def test_verification_notification_uses_exact_scenario_policy_and_target_specific_grants(
    postgres_engine: Engine,
) -> None:
    organization_id = OrganizationId(uuid4())
    submitter_id = UserId(uuid4())
    target_owner_id = UserId(uuid4())
    sibling_owner_id = UserId(uuid4())
    scenario_id = uuid4()
    scenario_version_id = uuid4()
    case_id = ReviewCaseId(uuid4())
    target_finding_id = FindingId(uuid4())
    sibling_finding_id = FindingId(uuid4())
    submission_id = SubmissionId(uuid4())
    activity_id = ActivityId(uuid4())
    scenario_key = ScenarioKey("target_owner_verifies")
    scenario_version = ScenarioVersion(7)

    custom_policy = replace(
        PROCESS_REVIEW_V1,
        scenario=Scenario(
            key=scenario_key,
            version=scenario_version,
            name="Target owner verifies",
        ),
        authorization=_TargetOwnerVerifies(),
    )
    registry = ScenarioRegistry()
    registry.register(custom_policy)

    with Session(postgres_engine) as session, session.begin():
        session.add(
            OrganizationRecord(
                id=organization_id,
                name=f"Scenario notification {organization_id}",
            )
        )
        session.flush()
        session.add_all(
            [
                UserRecord(
                    id=submitter_id,
                    organization_id=organization_id,
                    display_name="Submitter",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=target_owner_id,
                    organization_id=organization_id,
                    display_name="Target Owner",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=sibling_owner_id,
                    organization_id=organization_id,
                    display_name="Sibling Owner",
                    platform_role="ordinary_user",
                ),
            ]
        )
        session.flush()
        session.add(
            ScenarioRecord(
                id=scenario_id,
                organization_id=organization_id,
                key=scenario_key,
                name="Target owner verifies",
            )
        )
        session.flush()
        session.add(
            ScenarioVersionRecord(
                id=scenario_version_id,
                scenario_id=scenario_id,
                organization_id=organization_id,
                version=scenario_version,
                published_at=NOW,
            )
        )
        session.flush()
        session.add(
            ReviewCaseRecord(
                id=case_id,
                organization_id=organization_id,
                scenario_version_id=scenario_version_id,
                title="Target-specific verification",
                lifecycle="in_progress",
                scenario_data_json={},
                created_by=submitter_id,
                created_at=NOW,
            )
        )
        session.flush()
        session.add_all(
            [
                FindingRecord(
                    id=target_finding_id,
                    organization_id=organization_id,
                    case_id=case_id,
                    title="Target finding",
                    severity="high",
                    lifecycle="verifying",
                    raised_by=submitter_id,
                    raised_at=NOW,
                    scenario_data_json={},
                ),
                FindingRecord(
                    id=sibling_finding_id,
                    organization_id=organization_id,
                    case_id=case_id,
                    title="Sibling finding",
                    severity="medium",
                    lifecycle="open",
                    raised_by=submitter_id,
                    raised_at=NOW,
                    scenario_data_json={},
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                FindingParticipantRecord(
                    id=uuid4(),
                    organization_id=organization_id,
                    finding_id=target_finding_id,
                    user_id=target_owner_id,
                    role_key="owner",
                    assigned_at=NOW,
                ),
                FindingParticipantRecord(
                    id=uuid4(),
                    organization_id=organization_id,
                    finding_id=sibling_finding_id,
                    user_id=sibling_owner_id,
                    role_key="owner",
                    assigned_at=NOW,
                ),
            ]
        )
        session.flush()
        session.add(
            SubmissionRecord(
                id=submission_id,
                organization_id=organization_id,
                case_id=case_id,
                finding_id=target_finding_id,
                purpose="rectification",
                submitted_by=submitter_id,
                submitted_at=NOW,
                payload_json={"stage": "completion", "comment": "ready"},
            )
        )
        session.flush()
        session.add(
            ActivityRecord(
                id=activity_id,
                organization_id=organization_id,
                actor_id=submitter_id,
                event_type="finding.submitted_for_verification",
                occurred_at=NOW,
                submission_id=submission_id,
                metadata_json={"finding_id": str(target_finding_id)},
            )
        )
        session.flush()

        finding = Finding(
            id=target_finding_id,
            organization_id=organization_id,
            case_id=case_id,
            title="Target finding",
            description=None,
            severity=FindingSeverity.HIGH,
            lifecycle=FindingLifecycle.VERIFYING,
            raised_by=submitter_id,
            raised_at=NOW,
            scenario_data={},
        )
        submission = Submission(
            id=submission_id,
            organization_id=organization_id,
            case_id=case_id,
            finding_id=target_finding_id,
            purpose=SubmissionPurpose.RECTIFICATION,
            submitted_by=submitter_id,
            submitted_at=NOW,
            payload={"stage": "completion", "comment": "ready"},
        )
        NotificationOrchestrator(
            session,
            registry,
            build_notification_service(session),
        ).rectification_submitted(
            RectificationSubmissionResult(
                submission=submission,
                finding=finding,
                activity_id=activity_id,
            )
        )

    with Session(postgres_engine) as verification:
        assert _notification_recipients_for_origin(
            verification,
            organization_id,
            activity_id,
            NotificationKind.FINDING_SUBMITTED_FOR_VERIFICATION,
        ) == {target_owner_id}
