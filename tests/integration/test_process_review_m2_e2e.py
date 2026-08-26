import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pwdlib import PasswordHash
from sqlalchemy import Engine, create_engine, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from easyaudit_next.composition import (
    build_finding_lifecycle_service,
    build_rectification_service,
    build_review_planning_service,
    build_verification_closure_service,
)
from easyaudit_next.platform.application.authentication import AuthenticationService
from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.persistence.models import (
    DepartmentRecord,
    LocalCredentialRecord,
    OrganizationRecord,
    UserRecord,
)
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyAuthSessionRepository,
    SqlAlchemyLocalCredentialRepository,
    SqlAlchemyPlatformAuditRepository,
    SqlAlchemyUserRepository,
)
from easyaudit_next.review_core.domain.models import (
    AssignmentRole,
    DepartmentActor,
    FindingLifecycle,
    FindingSeverity,
    ReviewCaseLifecycle,
    ScenarioKey,
    ScenarioVersion,
    UserActor,
)
from easyaudit_next.review_core.persistence.models import (
    ActionItemRecord,
    ActivityRecord,
    EvidenceRecord,
    FindingRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
    SubmissionRecord,
)

NOW = datetime(2026, 8, 26, 17, 0, tzinfo=UTC)
PASSWORD = "m2-e2e-correct-horse-battery"


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _authentication_service(session: Session) -> AuthenticationService:
    return AuthenticationService(
        SqlAlchemyLocalCredentialRepository(session),
        SqlAlchemyAuthSessionRepository(session),
        SqlAlchemyUserRepository(session),
        SqlAlchemyPlatformAuditRepository(session),
    )


def _seed_process_review(
    engine: Engine,
) -> tuple[OrganizationId, DepartmentId, str, str, str]:
    organization_id = OrganizationId(uuid4())
    department_id = DepartmentId(uuid4())
    lead_id = UserId(uuid4())
    owner_id = UserId(uuid4())
    reviewer_id = UserId(uuid4())
    scenario_id = uuid4()
    suffix = uuid4().hex[:12]
    lead_login = f"m2-lead-{suffix}"
    owner_login = f"m2-owner-{suffix}"
    reviewer_login = f"m2-reviewer-{suffix}"
    password_hash = PasswordHash.recommended().hash(PASSWORD)

    with Session(engine) as session, session.begin():
        session.add(
            OrganizationRecord(
                id=organization_id,
                name=f"M2 E2E {organization_id}",
            )
        )
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
                    id=lead_id,
                    organization_id=organization_id,
                    display_name="M2 Lead",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=owner_id,
                    organization_id=organization_id,
                    primary_department_id=department_id,
                    display_name="M2 Owner",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=reviewer_id,
                    organization_id=organization_id,
                    display_name="M2 Reviewer",
                    platform_role="ordinary_user",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                LocalCredentialRecord(
                    user_id=lead_id,
                    organization_id=organization_id,
                    login_name=lead_login,
                    password_hash=password_hash,
                    password_changed_at=NOW,
                ),
                LocalCredentialRecord(
                    user_id=owner_id,
                    organization_id=organization_id,
                    login_name=owner_login,
                    password_hash=password_hash,
                    password_changed_at=NOW,
                ),
                LocalCredentialRecord(
                    user_id=reviewer_id,
                    organization_id=organization_id,
                    login_name=reviewer_login,
                    password_hash=password_hash,
                    password_changed_at=NOW,
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

    return organization_id, department_id, lead_login, owner_login, reviewer_login


def test_complete_authenticated_process_review_chain_closes_case(
    postgres_engine: Engine,
) -> None:
    organization_id, department_id, lead_login, owner_login, reviewer_login = (
        _seed_process_review(postgres_engine)
    )

    with Session(postgres_engine, expire_on_commit=False) as login_session:
        authentication = _authentication_service(login_session)
        lead_token = authentication.login(lead_login, PASSWORD, now=NOW).token
        owner_token = authentication.login(owner_login, PASSWORD, now=NOW).token
        reviewer_token = authentication.login(reviewer_login, PASSWORD, now=NOW).token
        login_session.commit()

    with Session(postgres_engine, expire_on_commit=False) as session:
        authentication = _authentication_service(session)
        _, lead = authentication.authenticate(lead_token, now=NOW)
        _, owner = authentication.authenticate(owner_token, now=NOW)
        _, reviewer = authentication.authenticate(reviewer_token, now=NOW)

        planning = build_review_planning_service(session)
        plan = planning.create_plan(lead, "M2 complete process review")
        review_case = planning.create_case(
            lead,
            ScenarioKey("process_review"),
            ScenarioVersion(1),
            "Assembly process review",
            {"area_code": "ASSY", "review_type": "routine"},
            plan_id=plan.id,
            occurred_at=NOW,
        )
        planning.add_case_member(
            lead,
            review_case.id,
            reviewer.id,
            "reviewer",
            occurred_at=NOW,
        )
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
        assert review_case.lifecycle is ReviewCaseLifecycle.IN_PROGRESS

        findings = build_finding_lifecycle_service(session)
        finding = findings.create_finding(
            lead,
            review_case.id,
            "Calibration status evidence is missing",
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
        finding = findings.transition_finding(
            lead,
            finding.id,
            "issue",
            occurred_at=NOW,
        )
        assert finding.lifecycle is FindingLifecycle.RECTIFYING

        rectification = build_rectification_service(session)
        plan_submission, _ = rectification.submit_rectification(
            owner,
            finding.id,
            "submit_plan",
            {
                "stage": "plan",
                "root_cause": "Calibration status card was not maintained after changeover",
            },
            occurred_at=NOW,
        )

        first_action = rectification.create_action_item(
            owner,
            finding.id,
            "Update calibration status card",
            occurred_at=NOW,
        )
        rectification.add_assignee(
            owner,
            first_action.id,
            UserActor(owner.id),
            AssignmentRole.PRIMARY,
            occurred_at=NOW,
        )
        first_action = rectification.transition_action_item(
            owner,
            first_action.id,
            "start",
            occurred_at=NOW,
        )
        first_action = rectification.transition_action_item(
            owner,
            first_action.id,
            "complete",
            occurred_at=NOW,
        )
        first_evidence = rectification.register_evidence(
            owner,
            first_action.id,
            "m2-e2e/calibration-status.jpg",
            "calibration-status.jpg",
            2048,
            "a" * 64,
            content_type="image/jpeg",
            description="Updated calibration status card",
            occurred_at=NOW,
        )

        second_action = rectification.create_action_item(
            owner,
            finding.id,
            "Add shift-start calibration confirmation",
            occurred_at=NOW,
        )
        rectification.add_assignee(
            owner,
            second_action.id,
            UserActor(owner.id),
            AssignmentRole.PRIMARY,
            occurred_at=NOW,
        )
        second_action = rectification.transition_action_item(
            owner,
            second_action.id,
            "start",
            occurred_at=NOW,
        )
        second_action = rectification.transition_action_item(
            owner,
            second_action.id,
            "complete",
            occurred_at=NOW,
        )
        second_evidence = rectification.register_evidence(
            owner,
            second_action.id,
            "m2-e2e/shift-confirmation.pdf",
            "shift-confirmation.pdf",
            4096,
            "b" * 64,
            content_type="application/pdf",
            description="Shift-start confirmation record",
            occurred_at=NOW,
        )

        first_completion, finding = rectification.submit_rectification(
            owner,
            finding.id,
            "submit_for_verification",
            {"stage": "completion", "comment": "Both corrective actions are complete"},
            occurred_at=NOW,
        )
        assert finding.lifecycle is FindingLifecycle.VERIFYING

        verification = build_verification_closure_service(session)
        reject_submission, finding = verification.submit_verification(
            reviewer,
            finding.id,
            "reject",
            {"result": "rejected", "comment": "Add evidence after one more shift"},
            occurred_at=NOW,
        )
        assert finding.lifecycle is FindingLifecycle.RECTIFYING

        first_action = rectification.transition_action_item(
            owner,
            first_action.id,
            "reopen",
            occurred_at=NOW,
        )
        rectification.register_evidence(
            owner,
            first_action.id,
            "m2-e2e/follow-up.jpg",
            "follow-up.jpg",
            1024,
            "c" * 64,
            content_type="image/jpeg",
            description="Follow-up evidence after the next shift",
            occurred_at=NOW,
        )
        first_action = rectification.transition_action_item(
            owner,
            first_action.id,
            "complete",
            occurred_at=NOW,
        )

        second_completion, finding = rectification.submit_rectification(
            owner,
            finding.id,
            "submit_for_verification",
            {"stage": "completion", "comment": "Follow-up evidence added"},
            occurred_at=NOW,
        )
        assert finding.lifecycle is FindingLifecycle.VERIFYING

        approve_submission, finding = verification.submit_verification(
            reviewer,
            finding.id,
            "approve",
            {"result": "approved", "comment": "Rectification verified"},
            occurred_at=NOW,
        )
        assert finding.lifecycle is FindingLifecycle.CLOSED

        review_case = planning.transition_case(
            lead,
            review_case.id,
            "finish_fieldwork",
            occurred_at=NOW,
        )
        assert review_case.lifecycle is ReviewCaseLifecycle.AWAITING_CLOSURE
        review_case = planning.transition_case(
            lead,
            review_case.id,
            "close",
            occurred_at=NOW,
        )
        assert review_case.lifecycle is ReviewCaseLifecycle.CLOSED
        session.commit()

    formal_submission_ids = {
        plan_submission.id,
        first_completion.id,
        reject_submission.id,
        second_completion.id,
        approve_submission.id,
    }
    with Session(postgres_engine) as verification_session:
        persisted_case = verification_session.scalar(
            select(ReviewCaseRecord).where(
                ReviewCaseRecord.organization_id == organization_id,
                ReviewCaseRecord.id == review_case.id,
            )
        )
        persisted_finding = verification_session.scalar(
            select(FindingRecord).where(
                FindingRecord.organization_id == organization_id,
                FindingRecord.id == finding.id,
            )
        )
        assert persisted_case is not None
        assert persisted_case.lifecycle == "closed"
        assert persisted_finding is not None
        assert persisted_finding.lifecycle == "closed"

        actions = tuple(
            verification_session.scalars(
                select(ActionItemRecord).where(
                    ActionItemRecord.organization_id == organization_id,
                    ActionItemRecord.finding_id == finding.id,
                )
            )
        )
        assert len(actions) == 2
        assert {action.lifecycle for action in actions} == {"done"}

        evidences = tuple(
            verification_session.scalars(
                select(EvidenceRecord).where(
                    EvidenceRecord.organization_id == organization_id,
                    EvidenceRecord.action_item_id.in_([first_action.id, second_action.id]),
                )
            )
        )
        assert {first_evidence.id, second_evidence.id}.issubset(
            {evidence.id for evidence in evidences}
        )
        assert len(evidences) == 3

        submissions = tuple(
            verification_session.scalars(
                select(SubmissionRecord).where(
                    SubmissionRecord.organization_id == organization_id,
                    SubmissionRecord.finding_id == finding.id,
                )
            )
        )
        assert len(submissions) == 5
        assert {submission.id for submission in submissions} == formal_submission_ids
        assert sum(submission.purpose == "rectification" for submission in submissions) == 3
        assert sum(submission.purpose == "verification" for submission in submissions) == 2

        submission_activity_count = verification_session.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(
                ActivityRecord.organization_id == organization_id,
                ActivityRecord.submission_id.in_(formal_submission_ids),
            )
        )
        assert submission_activity_count == 5
        case_transition_count = verification_session.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(
                ActivityRecord.organization_id == organization_id,
                ActivityRecord.review_case_id == review_case.id,
                ActivityRecord.event_type == "review_case.transitioned",
            )
        )
        assert case_transition_count == 4
        action_transition_count = verification_session.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(
                ActivityRecord.organization_id == organization_id,
                ActivityRecord.action_item_id.in_([first_action.id, second_action.id]),
                ActivityRecord.event_type == "action_item.transitioned",
            )
        )
        assert action_transition_count == 6

        version = verification_session.scalar(
            select(ScenarioVersionRecord.version)
            .join(
                ReviewCaseRecord,
                ReviewCaseRecord.scenario_version_id == ScenarioVersionRecord.id,
            )
            .where(ReviewCaseRecord.id == review_case.id)
        )
        assert version == 1

        immutable_submission_id = plan_submission.id

    with Session(postgres_engine) as mutation_session:
        with pytest.raises(DBAPIError, match="append-only"):
            mutation_session.execute(
                update(SubmissionRecord)
                .where(SubmissionRecord.id == immutable_submission_id)
                .values(payload_json={"tampered": True})
            )
            mutation_session.flush()
        mutation_session.rollback()

    with Session(postgres_engine) as verification_session:
        assert verification_session.scalar(
            select(func.count())
            .select_from(SubmissionRecord)
            .where(
                SubmissionRecord.organization_id == organization_id,
                SubmissionRecord.finding_id == finding.id,
            )
        ) == 5
