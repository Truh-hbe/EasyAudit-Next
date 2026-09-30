"""Seed an isolated Case team for M5.3 real-browser acceptance."""

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
    CaseMemberRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)

ORGANIZATION_ID = UUID("00000000-0000-4000-8000-0000000003B0")
LEAD_USER_ID = UUID("00000000-0000-4000-8000-0000000003B1")
CANDIDATE_USER_ID = UUID("00000000-0000-4000-8000-0000000003B2")
OBSERVER_USER_ID = UUID("00000000-0000-4000-8000-0000000003B6")
SCENARIO_ID = UUID("00000000-0000-4000-8000-0000000003B3")
SCENARIO_VERSION_ID = UUID("00000000-0000-4000-8000-0000000003B4")
CASE_ID = UUID("00000000-0000-4000-8000-0000000003B5")

LOGIN_NAME = "browser-m5-3-lead"
PASSWORD = "m5-3-browser-password-000"
OBSERVER_LOGIN_NAME = "browser-m5-3-observer"
OBSERVER_PASSWORD = "m5-3-observer-password-000"
PASSWORD_HASH = PasswordHash.recommended()
BASE_TIME = datetime(2026, 8, 30, 3, 0, tzinfo=UTC)


def main() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        with Session(engine) as session, session.begin():
            session.add(OrganizationRecord(id=ORGANIZATION_ID, name="M5.3 Browser Acceptance"))
            session.flush()
            session.add_all(
                [
                    UserRecord(
                        id=LEAD_USER_ID,
                        organization_id=ORGANIZATION_ID,
                        display_name="M5.3 Browser Team Lead",
                        platform_role="ordinary_user",
                    ),
                    UserRecord(
                        id=CANDIDATE_USER_ID,
                        organization_id=ORGANIZATION_ID,
                        display_name="M5.3 Browser Candidate",
                        platform_role="ordinary_user",
                    ),
                    UserRecord(
                        id=OBSERVER_USER_ID,
                        organization_id=ORGANIZATION_ID,
                        display_name="M5.3 Browser Observer",
                        platform_role="ordinary_user",
                    ),
                ]
            )
            session.flush()
            session.add(
                LocalCredentialRecord(
                    user_id=LEAD_USER_ID,
                    organization_id=ORGANIZATION_ID,
                    login_name=LOGIN_NAME,
                    password_hash=PASSWORD_HASH.hash(PASSWORD),
                    password_changed_at=BASE_TIME,
                    must_change_password=False,
                )
            )
            session.add(
                LocalCredentialRecord(
                    user_id=OBSERVER_USER_ID,
                    organization_id=ORGANIZATION_ID,
                    login_name=OBSERVER_LOGIN_NAME,
                    password_hash=PASSWORD_HASH.hash(OBSERVER_PASSWORD),
                    password_changed_at=BASE_TIME,
                    must_change_password=False,
                )
            )
            session.flush()
            session.add(ScenarioRecord(
                id=SCENARIO_ID,
                organization_id=ORGANIZATION_ID,
                key="process_review",
                name="Process Review",
            ))
            session.flush()
            session.add(ScenarioVersionRecord(
                id=SCENARIO_VERSION_ID,
                scenario_id=SCENARIO_ID,
                organization_id=ORGANIZATION_ID,
                version=1,
                published_at=BASE_TIME,
            ))
            session.flush()
            session.add(
                ReviewCaseRecord(
                    id=CASE_ID,
                    organization_id=ORGANIZATION_ID,
                    plan_id=None,
                    scenario_version_id=SCENARIO_VERSION_ID,
                    title="M5.3 Browser Team Case",
                    lifecycle="in_progress",
                    planned_start_at=BASE_TIME,
                    planned_end_at=datetime(2099, 12, 31, tzinfo=UTC),
                    started_at=BASE_TIME,
                    fieldwork_completed_at=None,
                    closed_at=None,
                    scenario_data_json={"area_code": "M53", "review_type": "routine"},
                    created_by=LEAD_USER_ID,
                    created_at=BASE_TIME,
                )
            )
            session.flush()
            session.add(
                CaseMemberRecord(
                    organization_id=ORGANIZATION_ID,
                    case_id=CASE_ID,
                    user_id=LEAD_USER_ID,
                    role_key="lead",
                    joined_at=BASE_TIME,
                )
            )
            session.add(
                CaseMemberRecord(
                    organization_id=ORGANIZATION_ID,
                    case_id=CASE_ID,
                    user_id=OBSERVER_USER_ID,
                    role_key="observer",
                    joined_at=BASE_TIME,
                )
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
