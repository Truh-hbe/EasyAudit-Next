"""Seed deterministic identities and M3.5 Product facts for real browser acceptance."""

import os
from datetime import UTC, datetime
from uuid import UUID

from pwdlib import PasswordHash
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from easyaudit_next.platform.persistence.models import (
    LocalCredentialRecord,
    OrganizationRecord,
    UserRecord,
)
from easyaudit_next.review_core.persistence.models import (
    ActionAssigneeRecord,
    ActionItemRecord,
    ActivityRecord,
    CaseMemberRecord,
    FindingParticipantRecord,
    FindingRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)

ORGANIZATION_ID = UUID("00000000-0000-4000-8000-000000000351")
ADMIN_USER_ID = UUID("00000000-0000-4000-8000-000000000352")
READY_USER_ID = UUID("00000000-0000-4000-8000-000000000353")
VIEWER_USER_ID = UUID("00000000-0000-4000-8000-000000000354")
MEMBER_USER_ID = UUID("00000000-0000-4000-8000-000000000355")
JOURNEY_LEAD_USER_ID = UUID("00000000-0000-4000-8000-000000000356")
JOURNEY_OWNER_USER_ID = UUID("00000000-0000-4000-8000-000000000357")
JOURNEY_REVIEWER_USER_ID = UUID("00000000-0000-4000-8000-000000000358")

SCENARIO_ID = UUID("00000000-0000-4000-8000-000000000360")
SCENARIO_VERSION_ID = UUID("00000000-0000-4000-8000-000000000361")

CASE_A_ID = UUID("00000000-0000-4000-8000-000000000370")
HIDDEN_H1_ID = UUID("00000000-0000-4000-8000-000000000371")
CASE_B_ID = UUID("00000000-0000-4000-8000-000000000372")
HIDDEN_H2_ID = UUID("00000000-0000-4000-8000-000000000373")
CASE_C_ID = UUID("00000000-0000-4000-8000-000000000374")
STALE_CASE_ID = UUID("00000000-0000-4000-8000-000000000375")
JOURNEY_CASE_ID = UUID("00000000-0000-4000-8000-000000000376")

FINDING_ID = UUID("00000000-0000-4000-8000-000000000380")
ACTION_ID = UUID("00000000-0000-4000-8000-000000000381")
FINDING_PARTICIPANT_ID = UUID("00000000-0000-4000-8000-000000000382")
ACTION_ASSIGNEE_ID = UUID("00000000-0000-4000-8000-000000000383")
JOURNEY_FINDING_ID = UUID("00000000-0000-4000-8000-000000000384")
JOURNEY_FINDING_PARTICIPANT_ID = UUID("00000000-0000-4000-8000-000000000385")
ACTIVITY_ID = UUID("00000000-0000-4000-8000-000000000390")

ADMIN_LOGIN_NAME = "browser-system-admin"
ADMIN_PASSWORD = "admin-password-000"
READY_LOGIN_NAME = "browser-ready-user"
READY_PASSWORD = "ready-password-000"
VIEWER_LOGIN_NAME = "browser-viewer-user"
VIEWER_PASSWORD = "viewer-password-000"
JOURNEY_LEAD_LOGIN_NAME = "browser-journey-lead"
JOURNEY_LEAD_PASSWORD = "lead-password-000"
JOURNEY_OWNER_LOGIN_NAME = "browser-journey-owner"
JOURNEY_OWNER_PASSWORD = "owner-password-000"
JOURNEY_REVIEWER_LOGIN_NAME = "browser-journey-reviewer"
JOURNEY_REVIEWER_PASSWORD = "reviewer-password-000"
PASSWORD_HASH = PasswordHash.recommended()

BASE_TIME = datetime(2026, 8, 28, 9, 0, tzinfo=UTC)


def _credential(*, user_id: UUID, login_name: str, password: str) -> LocalCredentialRecord:
    return LocalCredentialRecord(
        user_id=user_id,
        organization_id=ORGANIZATION_ID,
        login_name=login_name,
        password_hash=PASSWORD_HASH.hash(password),
        password_changed_at=BASE_TIME,
        must_change_password=False,
    )


def _case(
    *,
    case_id: UUID,
    title: str,
    created_at: datetime,
    created_by: UUID = READY_USER_ID,
) -> ReviewCaseRecord:
    return ReviewCaseRecord(
        id=case_id,
        organization_id=ORGANIZATION_ID,
        plan_id=None,
        scenario_version_id=SCENARIO_VERSION_ID,
        title=title,
        lifecycle="in_progress",
        planned_start_at=datetime(2026, 8, 20, tzinfo=UTC),
        planned_end_at=datetime(2099, 12, 31, tzinfo=UTC),
        started_at=datetime(2026, 8, 21, tzinfo=UTC),
        fieldwork_completed_at=None,
        closed_at=None,
        scenario_data_json={"area_code": "LINE-A", "review_type": "routine"},
        created_by=created_by,
        created_at=created_at,
    )


def main() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        with Session(engine) as session, session.begin():
            session.add(
                OrganizationRecord(
                    id=ORGANIZATION_ID,
                    name="M3.5 Browser Acceptance",
                )
            )
            session.flush()
            session.add_all(
                [
                    UserRecord(
                        id=ADMIN_USER_ID,
                        organization_id=ORGANIZATION_ID,
                        display_name="Browser System Admin",
                        platform_role="system_admin",
                    ),
                    UserRecord(
                        id=READY_USER_ID,
                        organization_id=ORGANIZATION_ID,
                        display_name="Browser Ready User",
                        platform_role="ordinary_user",
                    ),
                    UserRecord(
                        id=VIEWER_USER_ID,
                        organization_id=ORGANIZATION_ID,
                        display_name="Browser Viewer User",
                        platform_role="ordinary_user",
                    ),
                    UserRecord(
                        id=MEMBER_USER_ID,
                        organization_id=ORGANIZATION_ID,
                        display_name="Human Case Member",
                        platform_role="ordinary_user",
                    ),
                    UserRecord(
                        id=JOURNEY_LEAD_USER_ID,
                        organization_id=ORGANIZATION_ID,
                        display_name="M3.5.5 Journey Lead",
                        platform_role="ordinary_user",
                    ),
                    UserRecord(
                        id=JOURNEY_OWNER_USER_ID,
                        organization_id=ORGANIZATION_ID,
                        display_name="M3.5.5 Journey Owner",
                        platform_role="ordinary_user",
                    ),
                    UserRecord(
                        id=JOURNEY_REVIEWER_USER_ID,
                        organization_id=ORGANIZATION_ID,
                        display_name="M3.5.5 Journey Reviewer",
                        platform_role="ordinary_user",
                    ),
                ]
            )
            session.flush()
            session.add_all(
                [
                    _credential(
                        user_id=ADMIN_USER_ID,
                        login_name=ADMIN_LOGIN_NAME,
                        password=ADMIN_PASSWORD,
                    ),
                    _credential(
                        user_id=READY_USER_ID,
                        login_name=READY_LOGIN_NAME,
                        password=READY_PASSWORD,
                    ),
                    _credential(
                        user_id=VIEWER_USER_ID,
                        login_name=VIEWER_LOGIN_NAME,
                        password=VIEWER_PASSWORD,
                    ),
                    _credential(
                        user_id=JOURNEY_LEAD_USER_ID,
                        login_name=JOURNEY_LEAD_LOGIN_NAME,
                        password=JOURNEY_LEAD_PASSWORD,
                    ),
                    _credential(
                        user_id=JOURNEY_OWNER_USER_ID,
                        login_name=JOURNEY_OWNER_LOGIN_NAME,
                        password=JOURNEY_OWNER_PASSWORD,
                    ),
                    _credential(
                        user_id=JOURNEY_REVIEWER_USER_ID,
                        login_name=JOURNEY_REVIEWER_LOGIN_NAME,
                        password=JOURNEY_REVIEWER_PASSWORD,
                    ),
                ]
            )
            session.flush()

            session.add(
                ScenarioRecord(
                    id=SCENARIO_ID,
                    organization_id=ORGANIZATION_ID,
                    key="process_review",
                    name="Process Review",
                )
            )
            session.flush()
            session.add(
                ScenarioVersionRecord(
                    id=SCENARIO_VERSION_ID,
                    scenario_id=SCENARIO_ID,
                    organization_id=ORGANIZATION_ID,
                    version=1,
                    published_at=BASE_TIME,
                )
            )
            session.flush()

            cases = [
                _case(
                    case_id=CASE_A_ID,
                    title="Visible Product Case A",
                    created_at=datetime(2026, 8, 28, 9, 0, tzinfo=UTC),
                ),
                _case(
                    case_id=HIDDEN_H1_ID,
                    title="Hidden Candidate H1",
                    created_at=datetime(2026, 8, 28, 8, 59, tzinfo=UTC),
                ),
                _case(
                    case_id=CASE_B_ID,
                    title="Visible Product Case B",
                    created_at=datetime(2026, 8, 28, 8, 58, tzinfo=UTC),
                ),
                _case(
                    case_id=HIDDEN_H2_ID,
                    title="Hidden Candidate H2",
                    created_at=datetime(2026, 8, 28, 8, 57, tzinfo=UTC),
                ),
                _case(
                    case_id=CASE_C_ID,
                    title="Visible Product Case C",
                    created_at=datetime(2026, 8, 28, 8, 56, tzinfo=UTC),
                ),
                _case(
                    case_id=STALE_CASE_ID,
                    title="Viewer Stale Case",
                    created_at=datetime(2026, 8, 28, 8, 55, tzinfo=UTC),
                    created_by=VIEWER_USER_ID,
                ),
                _case(
                    case_id=JOURNEY_CASE_ID,
                    title="M3.5.5 End-to-End Product Case",
                    created_at=datetime(2026, 8, 28, 8, 54, tzinfo=UTC),
                    created_by=JOURNEY_LEAD_USER_ID,
                ),
            ]
            session.add_all(cases)
            session.flush()

            session.add_all(
                [
                    CaseMemberRecord(
                        organization_id=ORGANIZATION_ID,
                        case_id=CASE_A_ID,
                        user_id=READY_USER_ID,
                        role_key="lead",
                        joined_at=BASE_TIME,
                    ),
                    CaseMemberRecord(
                        organization_id=ORGANIZATION_ID,
                        case_id=CASE_A_ID,
                        user_id=MEMBER_USER_ID,
                        role_key="observer",
                        joined_at=BASE_TIME,
                    ),
                    CaseMemberRecord(
                        organization_id=ORGANIZATION_ID,
                        case_id=CASE_B_ID,
                        user_id=READY_USER_ID,
                        role_key="lead",
                        joined_at=BASE_TIME,
                    ),
                    CaseMemberRecord(
                        organization_id=ORGANIZATION_ID,
                        case_id=CASE_C_ID,
                        user_id=READY_USER_ID,
                        role_key="lead",
                        joined_at=BASE_TIME,
                    ),
                    CaseMemberRecord(
                        organization_id=ORGANIZATION_ID,
                        case_id=STALE_CASE_ID,
                        user_id=VIEWER_USER_ID,
                        role_key="observer",
                        joined_at=BASE_TIME,
                    ),
                    CaseMemberRecord(
                        organization_id=ORGANIZATION_ID,
                        case_id=JOURNEY_CASE_ID,
                        user_id=JOURNEY_LEAD_USER_ID,
                        role_key="lead",
                        joined_at=BASE_TIME,
                    ),
                    CaseMemberRecord(
                        organization_id=ORGANIZATION_ID,
                        case_id=JOURNEY_CASE_ID,
                        user_id=JOURNEY_REVIEWER_USER_ID,
                        role_key="reviewer",
                        joined_at=BASE_TIME,
                    ),
                ]
            )
            session.flush()

            session.add(
                FindingRecord(
                    id=FINDING_ID,
                    organization_id=ORGANIZATION_ID,
                    case_id=CASE_A_ID,
                    title="Real Browser Finding",
                    description="Server-owned finding description",
                    severity="high",
                    lifecycle="rectifying",
                    scenario_data_json={},
                    raised_by=READY_USER_ID,
                    raised_at=BASE_TIME,
                )
            )
            session.add(
                FindingRecord(
                    id=JOURNEY_FINDING_ID,
                    organization_id=ORGANIZATION_ID,
                    case_id=JOURNEY_CASE_ID,
                    title="M3.5.5 Multi-user Finding",
                    description="Final Product acceptance finding driven through Product commands.",
                    severity="high",
                    lifecycle="rectifying",
                    scenario_data_json={
                        "issue_type": "control_gap",
                        "project_category": "assembly",
                    },
                    raised_by=JOURNEY_LEAD_USER_ID,
                    raised_at=BASE_TIME,
                )
            )
            session.flush()
            session.add(
                FindingParticipantRecord(
                    id=FINDING_PARTICIPANT_ID,
                    organization_id=ORGANIZATION_ID,
                    finding_id=FINDING_ID,
                    user_id=READY_USER_ID,
                    department_id=None,
                    role_key="owner",
                    assigned_at=BASE_TIME,
                )
            )
            session.add(
                FindingParticipantRecord(
                    id=JOURNEY_FINDING_PARTICIPANT_ID,
                    organization_id=ORGANIZATION_ID,
                    finding_id=JOURNEY_FINDING_ID,
                    user_id=JOURNEY_OWNER_USER_ID,
                    department_id=None,
                    role_key="owner",
                    assigned_at=BASE_TIME,
                )
            )
            session.flush()
            session.add(
                ActionItemRecord(
                    id=ACTION_ID,
                    organization_id=ORGANIZATION_ID,
                    finding_id=FINDING_ID,
                    title="Real Browser Action",
                    lifecycle="todo",
                    due_at=None,
                    completed_at=None,
                )
            )
            session.flush()
            session.add(
                ActionAssigneeRecord(
                    id=ACTION_ASSIGNEE_ID,
                    organization_id=ORGANIZATION_ID,
                    action_item_id=ACTION_ID,
                    user_id=READY_USER_ID,
                    department_id=None,
                    role="primary",
                    assigned_at=BASE_TIME,
                )
            )
            session.flush()
            session.add(
                ActivityRecord(
                    id=ACTIVITY_ID,
                    organization_id=ORGANIZATION_ID,
                    actor_id=READY_USER_ID,
                    event_type="review_case.real_browser_seeded",
                    occurred_at=BASE_TIME,
                    review_case_id=CASE_A_ID,
                    finding_id=None,
                    action_item_id=None,
                    submission_id=None,
                    metadata_json={"secret": "must-not-reach-product-wire"},
                )
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
