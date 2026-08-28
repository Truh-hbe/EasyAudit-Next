import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session

from easyaudit_next.composition import (
    build_finding_lifecycle_service,
    build_rectification_service,
    build_review_planning_service,
    build_review_resource_context_query_service,
)
from easyaudit_next.notifications.persistence import NotificationRecord
from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import PlatformRole, User
from easyaudit_next.platform.persistence.models import (
    DepartmentRecord,
    OrganizationRecord,
    UserRecord,
)
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.application.review_planning import ReviewAuthorizationError
from easyaudit_next.review_core.domain.ids import ActionItemId, FindingId
from easyaudit_next.review_core.domain.models import (
    AssignmentRole,
    DepartmentActor,
    FindingSeverity,
    ScenarioKey,
    ScenarioVersion,
    UserActor,
)
from easyaudit_next.review_core.domain.scenario_capabilities import ActorKind
from easyaudit_next.review_core.persistence.models import (
    ActivityRecord,
    SubmissionRecord,
)

NOW = datetime(2026, 8, 28, 14, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _actor(
    user_id: UserId,
    organization_id: OrganizationId,
    display_name: str,
    *,
    platform_role: PlatformRole = PlatformRole.ORDINARY_USER,
) -> User:
    return User(
        id=user_id,
        organization_id=organization_id,
        display_name=display_name,
        platform_role=platform_role,
        primary_department_id=None,
    )


def _seed_collaboration_shape(engine: Engine) -> dict[str, object]:
    organization_id = OrganizationId(uuid4())
    department_id = DepartmentId(uuid4())
    lead_id = UserId(uuid4())
    owner_id = UserId(uuid4())
    assignee_id = UserId(uuid4())
    candidate_id = UserId(uuid4())
    unrelated_id = UserId(uuid4())
    admin_id = UserId(uuid4())
    scenario_id = uuid4()

    with Session(engine) as session, session.begin():
        session.add(OrganizationRecord(id=organization_id, name=f"M3.5.3 {organization_id}"))
        session.flush()
        session.add(
            DepartmentRecord(
                id=department_id,
                organization_id=organization_id,
                name="Corrective Operations",
            )
        )
        session.flush()
        session.add_all(
            [
                UserRecord(
                    id=lead_id,
                    organization_id=organization_id,
                    display_name="Collaboration Lead",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=owner_id,
                    organization_id=organization_id,
                    display_name="Finding Owner",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=assignee_id,
                    organization_id=organization_id,
                    display_name="Action Assignee",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=candidate_id,
                    organization_id=organization_id,
                    display_name="Candidate Engineer",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=unrelated_id,
                    organization_id=organization_id,
                    display_name="Unrelated Engineer",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=admin_id,
                    organization_id=organization_id,
                    display_name="Unrelated Platform Admin",
                    platform_role="system_admin",
                ),
            ]
        )
        session.flush()
        session.add(
            __import__(
                "easyaudit_next.review_core.persistence.models",
                fromlist=["ScenarioRecord"],
            ).ScenarioRecord(
                id=scenario_id,
                organization_id=organization_id,
                key="process_review",
                name="Process Review",
            )
        )
        session.flush()
        session.add(
            __import__(
                "easyaudit_next.review_core.persistence.models",
                fromlist=["ScenarioVersionRecord"],
            ).ScenarioVersionRecord(
                id=uuid4(),
                scenario_id=scenario_id,
                organization_id=organization_id,
                version=1,
                published_at=NOW,
            )
        )

    with Session(engine, expire_on_commit=False) as session, session.begin():
        users = SqlAlchemyUserRepository(session)
        lead = users.get(lead_id)
        owner = users.get(owner_id)
        assignee = users.get(assignee_id)
        assert lead is not None and owner is not None and assignee is not None

        planning = build_review_planning_service(session)
        review_case = planning.create_case(
            lead,
            ScenarioKey("process_review"),
            ScenarioVersion(1),
            "M3.5.3 Collaboration Case",
            {"area_code": "ASSY", "review_type": "routine"},
            occurred_at=NOW,
        )
        review_case = planning.transition_case(lead, review_case.id, "schedule", occurred_at=NOW)
        review_case = planning.transition_case(lead, review_case.id, "start", occurred_at=NOW)

        findings = build_finding_lifecycle_service(session)
        finding = findings.create_finding(
            lead,
            review_case.id,
            "Torque record missing",
            FindingSeverity.HIGH,
            {"issue_type": "control_gap", "project_category": "assembly"},
            occurred_at=NOW,
        )
        findings.add_participant(
            lead,
            finding.id,
            UserActor(owner.id),
            "owner",
            occurred_at=NOW,
        )
        findings.add_participant(
            lead,
            finding.id,
            DepartmentActor(department_id),
            "responsible_department",
            occurred_at=NOW,
        )
        finding = findings.transition_finding(lead, finding.id, "issue", occurred_at=NOW)

        sibling = findings.create_finding(
            lead,
            review_case.id,
            "Sibling finding",
            FindingSeverity.LOW,
            {"issue_type": "observation", "project_category": "assembly"},
            occurred_at=NOW,
        )

        rectification = build_rectification_service(session)
        action = rectification.create_action_item(
            owner,
            finding.id,
            "Restore torque traceability",
            due_at=NOW + timedelta(days=3),
            occurred_at=NOW,
        )
        rectification.add_assignee(
            owner,
            action.id,
            UserActor(assignee.id),
            AssignmentRole.PRIMARY,
            occurred_at=NOW,
        )

        target_submission_1 = UUID("00000000-0000-0000-0000-000000000211")
        target_submission_2 = UUID("00000000-0000-0000-0000-000000000212")
        session.add_all(
            [
                SubmissionRecord(
                    id=target_submission_2,
                    organization_id=organization_id,
                    case_id=review_case.id,
                    finding_id=finding.id,
                    purpose="verification",
                    submitted_by=lead_id,
                    submitted_at=NOW + timedelta(seconds=2),
                    payload_json={"result": "approved"},
                ),
                SubmissionRecord(
                    id=target_submission_1,
                    organization_id=organization_id,
                    case_id=review_case.id,
                    finding_id=finding.id,
                    purpose="rectification",
                    submitted_by=owner_id,
                    submitted_at=NOW + timedelta(seconds=1),
                    payload_json={"stage": "plan", "root_cause": "gap"},
                ),
                SubmissionRecord(
                    id=uuid4(),
                    organization_id=organization_id,
                    case_id=review_case.id,
                    finding_id=sibling.id,
                    purpose="rectification",
                    submitted_by=lead_id,
                    submitted_at=NOW,
                    payload_json={"sibling": True},
                ),
                SubmissionRecord(
                    id=uuid4(),
                    organization_id=organization_id,
                    case_id=review_case.id,
                    finding_id=None,
                    purpose="closure",
                    submitted_by=lead_id,
                    submitted_at=NOW,
                    payload_json={"case_only": True},
                ),
            ]
        )
        session.flush()
        finding_activity_id = UUID("00000000-0000-0000-0000-000000000221")
        action_activity_id = UUID("00000000-0000-0000-0000-000000000222")
        sibling_activity_id = UUID("00000000-0000-0000-0000-000000000223")
        submission_activity_id = UUID("00000000-0000-0000-0000-000000000224")
        session.add_all(
            [
                ActivityRecord(
                    id=finding_activity_id,
                    organization_id=organization_id,
                    actor_id=lead_id,
                    event_type="finding.presentation_fact",
                    occurred_at=NOW + timedelta(minutes=1),
                    review_case_id=None,
                    finding_id=finding.id,
                    action_item_id=None,
                    submission_id=None,
                    metadata_json={"private": "not projected"},
                ),
                ActivityRecord(
                    id=action_activity_id,
                    organization_id=organization_id,
                    actor_id=owner_id,
                    event_type="action_item.presentation_fact",
                    occurred_at=NOW + timedelta(minutes=1),
                    review_case_id=None,
                    finding_id=None,
                    action_item_id=action.id,
                    submission_id=None,
                    metadata_json={"private": "not projected"},
                ),
                ActivityRecord(
                    id=sibling_activity_id,
                    organization_id=organization_id,
                    actor_id=lead_id,
                    event_type="finding.sibling_fact",
                    occurred_at=NOW + timedelta(minutes=2),
                    review_case_id=None,
                    finding_id=sibling.id,
                    action_item_id=None,
                    submission_id=None,
                    metadata_json={},
                ),
                ActivityRecord(
                    id=submission_activity_id,
                    organization_id=organization_id,
                    actor_id=lead_id,
                    event_type="submission.fact",
                    occurred_at=NOW + timedelta(minutes=3),
                    review_case_id=None,
                    finding_id=None,
                    action_item_id=None,
                    submission_id=target_submission_1,
                    metadata_json={},
                ),
            ]
        )

    return {
        "organization_id": organization_id,
        "department_id": department_id,
        "lead_id": lead_id,
        "owner_id": owner_id,
        "assignee_id": assignee_id,
        "candidate_id": candidate_id,
        "unrelated_id": unrelated_id,
        "admin_id": admin_id,
        "finding_id": FindingId(finding.id),
        "sibling_id": FindingId(sibling.id),
        "action_id": ActionItemId(action.id),
        "submission_ids": (target_submission_1, target_submission_2),
        "finding_activity_id": finding_activity_id,
        "action_activity_id": action_activity_id,
    }


def test_target_scoped_relationship_views_and_candidates(postgres_engine: Engine) -> None:
    seeded = _seed_collaboration_shape(postgres_engine)
    organization_id = seeded["organization_id"]
    assert isinstance(organization_id, UUID)
    lead_id = seeded["lead_id"]
    owner_id = seeded["owner_id"]
    unrelated_id = seeded["unrelated_id"]
    admin_id = seeded["admin_id"]
    finding_id = seeded["finding_id"]
    action_id = seeded["action_id"]
    assert isinstance(lead_id, UUID)
    assert isinstance(owner_id, UUID)
    assert isinstance(unrelated_id, UUID)
    assert isinstance(admin_id, UUID)
    assert isinstance(finding_id, UUID)
    assert isinstance(action_id, UUID)

    lead = _actor(UserId(lead_id), OrganizationId(organization_id), "Collaboration Lead")
    owner = _actor(UserId(owner_id), OrganizationId(organization_id), "Finding Owner")
    unrelated = _actor(UserId(unrelated_id), OrganizationId(organization_id), "Unrelated Engineer")
    admin = _actor(
        UserId(admin_id),
        OrganizationId(organization_id),
        "Unrelated Platform Admin",
        platform_role=PlatformRole.SYSTEM_ADMIN,
    )

    with Session(postgres_engine) as session:
        service = build_review_resource_context_query_service(session)
        participant_views = service.list_finding_participant_views(lead, FindingId(finding_id))
        assert {(item.actor_kind, item.display_name) for item in participant_views} == {
            (ActorKind.USER, "Finding Owner"),
            (ActorKind.DEPARTMENT, "Corrective Operations"),
        }
        assignee_views = service.list_action_assignee_views(owner, ActionItemId(action_id))
        assert [(item.actor_kind, item.display_name) for item in assignee_views] == [
            (ActorKind.USER, "Action Assignee")
        ]

        candidates = service.search_finding_participant_candidates(
            lead,
            FindingId(finding_id),
            role_key="collaborator",
            actor_kind=ActorKind.USER,
            search_text="Candidate",
            limit=20,
        )
        assert [(item.actor_kind, item.display_name) for item in candidates] == [
            (ActorKind.USER, "Candidate Engineer")
        ]
        with pytest.raises(ValueError):
            service.search_finding_participant_candidates(
                lead,
                FindingId(finding_id),
                role_key="responsible_department",
                actor_kind=ActorKind.USER,
                search_text="Candidate",
                limit=20,
            )
        with pytest.raises(ValueError):
            service.search_action_assignee_candidates(
                owner,
                ActionItemId(action_id),
                role=AssignmentRole.PRIMARY,
                actor_kind=ActorKind.DEPARTMENT,
                search_text="Corrective",
                limit=20,
            )
        with pytest.raises(ValueError):
            service.search_finding_participant_candidates(
                lead,
                FindingId(finding_id),
                role_key="collaborator",
                actor_kind=ActorKind.USER,
                search_text="%",
                limit=20,
            )
        with pytest.raises(ReviewAuthorizationError):
            service.search_finding_participant_candidates(
                unrelated,
                FindingId(finding_id),
                role_key="collaborator",
                actor_kind=ActorKind.USER,
                search_text="Candidate",
                limit=20,
            )
        with pytest.raises(ReviewAuthorizationError):
            service.search_finding_participant_candidates(
                admin,
                FindingId(finding_id),
                role_key="collaborator",
                actor_kind=ActorKind.USER,
                search_text="Candidate",
                limit=20,
            )


def test_finding_submission_and_activity_reads_are_exact_and_side_effect_free(
    postgres_engine: Engine,
) -> None:
    seeded = _seed_collaboration_shape(postgres_engine)
    organization_id = seeded["organization_id"]
    lead_id = seeded["lead_id"]
    owner_id = seeded["owner_id"]
    finding_id = seeded["finding_id"]
    action_id = seeded["action_id"]
    assert isinstance(organization_id, UUID)
    assert isinstance(lead_id, UUID)
    assert isinstance(owner_id, UUID)
    assert isinstance(finding_id, UUID)
    assert isinstance(action_id, UUID)
    lead = _actor(UserId(lead_id), OrganizationId(organization_id), "Collaboration Lead")
    owner = _actor(UserId(owner_id), OrganizationId(organization_id), "Finding Owner")

    with Session(postgres_engine) as session:
        activity_before = session.scalar(
            select(func.count()).select_from(ActivityRecord).where(
                ActivityRecord.organization_id == organization_id
            )
        )
        notification_before = session.scalar(
            select(func.count()).select_from(NotificationRecord).where(
                NotificationRecord.organization_id == organization_id
            )
        )
        service = build_review_resource_context_query_service(session)
        submissions = service.list_finding_submissions(lead, FindingId(finding_id))
        finding_activities = service.list_finding_activities(lead, FindingId(finding_id))
        action_activities = service.list_action_activities(owner, ActionItemId(action_id))
        activity_after = session.scalar(
            select(func.count()).select_from(ActivityRecord).where(
                ActivityRecord.organization_id == organization_id
            )
        )
        notification_after = session.scalar(
            select(func.count()).select_from(NotificationRecord).where(
                NotificationRecord.organization_id == organization_id
            )
        )

    expected_submission_ids = seeded["submission_ids"]
    assert isinstance(expected_submission_ids, tuple)
    assert tuple(item.id for item in submissions) == expected_submission_ids
    assert seeded["finding_activity_id"] in {item.id for item in finding_activities}
    assert seeded["action_activity_id"] in {item.id for item in action_activities}
    assert all(item.subject_id == finding_id for item in finding_activities)
    assert all(item.subject_id == action_id for item in action_activities)
    assert activity_after == activity_before
    assert notification_after == notification_before
