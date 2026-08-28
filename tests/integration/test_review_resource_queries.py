import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session

from easyaudit_next.api.dependencies import (
    CurrentIdentity,
    get_current_identity,
    get_database_session,
)
from easyaudit_next.composition import (
    build_finding_lifecycle_service,
    build_rectification_service,
    build_review_planning_service,
    build_review_resource_context_query_service,
)
from easyaudit_next.main import create_app
from easyaudit_next.notifications.persistence import NotificationRecord
from easyaudit_next.platform.domain.ids import AuthSessionId, DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import AuthSession, PlatformRole, User
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
    ScenarioRecord,
    ScenarioVersionRecord,
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


@dataclass(frozen=True, slots=True)
class SeededCollaboration:
    organization_id: OrganizationId
    department_id: DepartmentId
    lead_id: UserId
    owner_id: UserId
    assignee_id: UserId
    candidate_id: UserId
    unrelated_id: UserId
    admin_id: UserId
    finding_id: FindingId
    sibling_id: FindingId
    action_id: ActionItemId
    submission_ids: tuple[object, object]
    finding_activity_id: object
    action_activity_id: object


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


def _identity(
    user: User,
) -> CurrentIdentity:
    return CurrentIdentity(
        auth_session=AuthSession(
            id=AuthSessionId(uuid4()),
            organization_id=user.organization_id,
            user_id=user.id,
            token_hash="a" * 64,
            expires_at=NOW + timedelta(hours=1),
            created_at=NOW,
        ),
        user=user,
    )


def _seed_collaboration_shape(engine: Engine) -> SeededCollaboration:
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

        target_submission_1 = uuid4()
        target_submission_2 = uuid4()
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

        finding_activity_id = uuid4()
        action_activity_id = uuid4()
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
                    id=uuid4(),
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
                    id=uuid4(),
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

    return SeededCollaboration(
        organization_id=organization_id,
        department_id=department_id,
        lead_id=lead_id,
        owner_id=owner_id,
        assignee_id=assignee_id,
        candidate_id=candidate_id,
        unrelated_id=unrelated_id,
        admin_id=admin_id,
        finding_id=FindingId(finding.id),
        sibling_id=FindingId(sibling.id),
        action_id=ActionItemId(action.id),
        submission_ids=(target_submission_1, target_submission_2),
        finding_activity_id=finding_activity_id,
        action_activity_id=action_activity_id,
    )


def test_target_scoped_relationship_views_and_candidates(postgres_engine: Engine) -> None:
    seeded = _seed_collaboration_shape(postgres_engine)
    lead = _actor(seeded.lead_id, seeded.organization_id, "Collaboration Lead")
    owner = _actor(seeded.owner_id, seeded.organization_id, "Finding Owner")
    unrelated = _actor(seeded.unrelated_id, seeded.organization_id, "Unrelated Engineer")
    admin = _actor(
        seeded.admin_id,
        seeded.organization_id,
        "Unrelated Platform Admin",
        platform_role=PlatformRole.SYSTEM_ADMIN,
    )

    with Session(postgres_engine) as session:
        service = build_review_resource_context_query_service(session)
        participant_views = service.list_finding_participant_views(lead, seeded.finding_id)
        assert {(item.actor_kind, item.display_name) for item in participant_views} == {
            (ActorKind.USER, "Finding Owner"),
            (ActorKind.DEPARTMENT, "Corrective Operations"),
        }
        assignee_views = service.list_action_assignee_views(owner, seeded.action_id)
        assert [(item.actor_kind, item.display_name) for item in assignee_views] == [
            (ActorKind.USER, "Action Assignee")
        ]

        candidates = service.search_finding_participant_candidates(
            lead,
            seeded.finding_id,
            role_key="collaborator",
            actor_kind=ActorKind.USER,
            search_text="Candidate",
            limit=20,
        )
        assert [(item.actor_kind, item.display_name) for item in candidates] == [
            (ActorKind.USER, "Candidate Engineer")
        ]
        action_candidates = service.search_action_assignee_candidates(
            owner,
            seeded.action_id,
            role=AssignmentRole.COLLABORATOR,
            actor_kind=ActorKind.USER,
            search_text="Candidate",
            limit=20,
        )
        assert [(item.actor_kind, item.display_name) for item in action_candidates] == [
            (ActorKind.USER, "Candidate Engineer")
        ]

        with pytest.raises(ValueError):
            service.search_finding_participant_candidates(
                lead,
                seeded.finding_id,
                role_key="responsible_department",
                actor_kind=ActorKind.USER,
                search_text="Candidate",
                limit=20,
            )
        with pytest.raises(ValueError):
            service.search_action_assignee_candidates(
                owner,
                seeded.action_id,
                role=AssignmentRole.PRIMARY,
                actor_kind=ActorKind.DEPARTMENT,
                search_text="Corrective",
                limit=20,
            )
        with pytest.raises(ValueError):
            service.search_finding_participant_candidates(
                lead,
                seeded.finding_id,
                role_key="collaborator",
                actor_kind=ActorKind.USER,
                search_text="%",
                limit=20,
            )
        with pytest.raises(ReviewAuthorizationError):
            service.search_finding_participant_candidates(
                unrelated,
                seeded.finding_id,
                role_key="collaborator",
                actor_kind=ActorKind.USER,
                search_text="Candidate",
                limit=20,
            )
        with pytest.raises(ReviewAuthorizationError):
            service.search_finding_participant_candidates(
                admin,
                seeded.finding_id,
                role_key="collaborator",
                actor_kind=ActorKind.USER,
                search_text="Candidate",
                limit=20,
            )


def test_finding_submission_and_activity_reads_are_exact_and_side_effect_free(
    postgres_engine: Engine,
) -> None:
    seeded = _seed_collaboration_shape(postgres_engine)
    lead = _actor(seeded.lead_id, seeded.organization_id, "Collaboration Lead")
    owner = _actor(seeded.owner_id, seeded.organization_id, "Finding Owner")

    with Session(postgres_engine) as session:
        activity_before = session.scalar(
            select(func.count()).select_from(ActivityRecord).where(
                ActivityRecord.organization_id == seeded.organization_id
            )
        )
        notification_before = session.scalar(
            select(func.count()).select_from(NotificationRecord).where(
                NotificationRecord.organization_id == seeded.organization_id
            )
        )
        service = build_review_resource_context_query_service(session)
        submissions = service.list_finding_submissions(lead, seeded.finding_id)
        finding_activities = service.list_finding_activities(lead, seeded.finding_id)
        action_activities = service.list_action_activities(owner, seeded.action_id)
        activity_after = session.scalar(
            select(func.count()).select_from(ActivityRecord).where(
                ActivityRecord.organization_id == seeded.organization_id
            )
        )
        notification_after = session.scalar(
            select(func.count()).select_from(NotificationRecord).where(
                NotificationRecord.organization_id == seeded.organization_id
            )
        )

    assert tuple(item.id for item in submissions) == seeded.submission_ids
    assert seeded.finding_activity_id in {item.id for item in finding_activities}
    assert seeded.action_activity_id in {item.id for item in action_activities}
    assert all(item.subject_id == seeded.finding_id for item in finding_activities)
    assert all(item.subject_id == seeded.action_id for item in action_activities)
    assert activity_after == activity_before
    assert notification_after == notification_before


def test_resource_query_http_contract_is_target_scoped(postgres_engine: Engine) -> None:
    seeded = _seed_collaboration_shape(postgres_engine)
    lead = _actor(seeded.lead_id, seeded.organization_id, "Collaboration Lead")
    owner = _actor(seeded.owner_id, seeded.organization_id, "Finding Owner")
    admin = _actor(
        seeded.admin_id,
        seeded.organization_id,
        "Unrelated Platform Admin",
        platform_role=PlatformRole.SYSTEM_ADMIN,
    )

    app = create_app()

    def database_override() -> Iterator[Session]:
        with Session(postgres_engine) as session:
            yield session

    app.dependency_overrides[get_database_session] = database_override
    app.dependency_overrides[get_current_identity] = lambda: _identity(lead)
    with TestClient(app) as client:
        participant_response = client.get(
            f"/api/v1/findings/{seeded.finding_id}/participant-views"
        )
        assert participant_response.status_code == 200
        assert {item["display_name"] for item in participant_response.json()} == {
            "Finding Owner",
            "Corrective Operations",
        }

        submission_response = client.get(
            f"/api/v1/findings/{seeded.finding_id}/submissions"
        )
        assert submission_response.status_code == 200
        assert tuple(item["id"] for item in submission_response.json()) == tuple(
            str(item) for item in seeded.submission_ids
        )

        candidate_response = client.get(
            f"/api/v1/findings/{seeded.finding_id}/participant-candidates",
            params={
                "role_key": "collaborator",
                "actor_kind": "user",
                "q": "Candidate",
                "limit": 20,
            },
        )
        assert candidate_response.status_code == 200
        assert [item["display_name"] for item in candidate_response.json()] == [
            "Candidate Engineer"
        ]

        invalid_kind_response = client.get(
            f"/api/v1/findings/{seeded.finding_id}/participant-candidates",
            params={
                "role_key": "responsible_department",
                "actor_kind": "user",
                "q": "Candidate",
            },
        )
        assert invalid_kind_response.status_code == 422

    app.dependency_overrides[get_current_identity] = lambda: _identity(owner)
    with TestClient(app) as client:
        action_candidate_response = client.get(
            f"/api/v1/action-items/{seeded.action_id}/assignee-candidates",
            params={
                "role": "collaborator",
                "actor_kind": "user",
                "q": "Candidate",
            },
        )
        assert action_candidate_response.status_code == 200
        assert [item["display_name"] for item in action_candidate_response.json()] == [
            "Candidate Engineer"
        ]

    app.dependency_overrides[get_current_identity] = lambda: _identity(admin)
    with TestClient(app) as client:
        forbidden_response = client.get(
            f"/api/v1/findings/{seeded.finding_id}/participant-candidates",
            params={
                "role_key": "collaborator",
                "actor_kind": "user",
                "q": "Candidate",
            },
        )
        assert forbidden_response.status_code == 403
