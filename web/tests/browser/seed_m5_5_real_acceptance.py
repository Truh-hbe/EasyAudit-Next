"""Seed only the deterministic support facts for the M5.5 browser journey.

Clean bootstrap is proved by the isolated PostgreSQL integration test. This
fixture intentionally prepares the shared browser database with an admin,
published exact scenarios, and foreign-object fixtures for isolation checks.
"""

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
    ReviewPlanRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)

ORGANIZATION_ID = UUID("00000000-0000-4000-8000-000000000550")
ADMIN_USER_ID = UUID("00000000-0000-4000-8000-000000000551")
PROCESS_SCENARIO_ID = UUID("00000000-0000-4000-8000-000000000552")
PROCESS_VERSION_ID = UUID("00000000-0000-4000-8000-000000000553")
COMPLIANCE_SCENARIO_ID = UUID("00000000-0000-4000-8000-000000000554")
COMPLIANCE_VERSION_ID = UUID("00000000-0000-4000-8000-000000000555")
ADMIN_CASE_ID = UUID("00000000-0000-4000-8000-000000000556")
FOREIGN_ORGANIZATION_ID = UUID("00000000-0000-4000-8000-000000000560")
FOREIGN_USER_ID = UUID("00000000-0000-4000-8000-000000000561")
FOREIGN_SCENARIO_ID = UUID("00000000-0000-4000-8000-000000000562")
FOREIGN_VERSION_ID = UUID("00000000-0000-4000-8000-000000000563")
FOREIGN_PLAN_ID = UUID("00000000-0000-4000-8000-000000000564")
FOREIGN_CASE_ID = UUID("00000000-0000-4000-8000-000000000565")

ADMIN_LOGIN_NAME = "browser-m5-5-admin"
ADMIN_PASSWORD = "m5-5-browser-admin-password-000"
BASE_TIME = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
PASSWORD_HASH = PasswordHash.recommended()


def main() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        with Session(engine) as session, session.begin():
            session.add_all(
                [
                    OrganizationRecord(
                        id=ORGANIZATION_ID,
                        name="M5.5 Browser Controlled Pilot",
                    ),
                    OrganizationRecord(
                        id=FOREIGN_ORGANIZATION_ID,
                        name="M5.5 Browser Foreign Organization",
                    ),
                ]
            )
            session.flush()
            session.add_all(
                [
                    UserRecord(
                        id=ADMIN_USER_ID,
                        organization_id=ORGANIZATION_ID,
                        display_name="M5.5 Browser System Administrator",
                        platform_role="system_admin",
                    ),
                    UserRecord(
                        id=FOREIGN_USER_ID,
                        organization_id=FOREIGN_ORGANIZATION_ID,
                        display_name="M5.5 Foreign Candidate Name",
                        platform_role="ordinary_user",
                    ),
                ]
            )
            session.flush()
            session.add(
                LocalCredentialRecord(
                    user_id=ADMIN_USER_ID,
                    organization_id=ORGANIZATION_ID,
                    login_name=ADMIN_LOGIN_NAME,
                    password_hash=PASSWORD_HASH.hash(ADMIN_PASSWORD),
                    password_changed_at=BASE_TIME,
                    must_change_password=False,
                )
            )
            session.flush()
            session.add_all(
                [
                    ScenarioRecord(
                        id=PROCESS_SCENARIO_ID,
                        organization_id=ORGANIZATION_ID,
                        key="process_review",
                        name="Process Review",
                    ),
                    ScenarioVersionRecord(
                        id=PROCESS_VERSION_ID,
                        scenario_id=PROCESS_SCENARIO_ID,
                        organization_id=ORGANIZATION_ID,
                        version=1,
                        published_at=BASE_TIME,
                    ),
                    ScenarioRecord(
                        id=COMPLIANCE_SCENARIO_ID,
                        organization_id=ORGANIZATION_ID,
                        key="compliance_review",
                        name="Compliance Review",
                    ),
                    ScenarioVersionRecord(
                        id=COMPLIANCE_VERSION_ID,
                        scenario_id=COMPLIANCE_SCENARIO_ID,
                        organization_id=ORGANIZATION_ID,
                        version=1,
                        published_at=BASE_TIME,
                    ),
                    ScenarioRecord(
                        id=FOREIGN_SCENARIO_ID,
                        organization_id=FOREIGN_ORGANIZATION_ID,
                        key="process_review",
                        name="Foreign Process Review",
                    ),
                    ScenarioVersionRecord(
                        id=FOREIGN_VERSION_ID,
                        scenario_id=FOREIGN_SCENARIO_ID,
                        organization_id=FOREIGN_ORGANIZATION_ID,
                        version=1,
                        published_at=BASE_TIME,
                    ),
                ]
            )
            session.flush()
            session.add(
                ReviewCaseRecord(
                    id=ADMIN_CASE_ID,
                    organization_id=ORGANIZATION_ID,
                    plan_id=None,
                    scenario_version_id=PROCESS_VERSION_ID,
                    title="M5.5 Administrator Has No Case Role",
                    lifecycle="draft",
                    planned_start_at=None,
                    planned_end_at=None,
                    started_at=None,
                    fieldwork_completed_at=None,
                    closed_at=None,
                    scenario_data_json={"area_code": "M55-ADMIN", "review_type": "pilot"},
                    created_by=ADMIN_USER_ID,
                    created_at=BASE_TIME,
                )
            )
            session.add(
                ReviewPlanRecord(
                    id=FOREIGN_PLAN_ID,
                    organization_id=FOREIGN_ORGANIZATION_ID,
                    title="M5.5 Foreign Plan Must Stay Hidden",
                    planned_start_at=None,
                    planned_end_at=None,
                    created_by=FOREIGN_USER_ID,
                    created_at=BASE_TIME,
                )
            )
            session.flush()
            session.add(
                ReviewCaseRecord(
                    id=FOREIGN_CASE_ID,
                    organization_id=FOREIGN_ORGANIZATION_ID,
                    plan_id=FOREIGN_PLAN_ID,
                    scenario_version_id=FOREIGN_VERSION_ID,
                    title="M5.5 Foreign Case Must Stay Hidden",
                    lifecycle="draft",
                    planned_start_at=None,
                    planned_end_at=None,
                    started_at=None,
                    fieldwork_completed_at=None,
                    closed_at=None,
                    scenario_data_json={"area_code": "FOREIGN", "review_type": "hidden"},
                    created_by=FOREIGN_USER_ID,
                    created_at=BASE_TIME,
                )
            )
            session.flush()
            session.add(
                CaseMemberRecord(
                    organization_id=FOREIGN_ORGANIZATION_ID,
                    case_id=FOREIGN_CASE_ID,
                    user_id=FOREIGN_USER_ID,
                    role_key="lead",
                    joined_at=BASE_TIME,
                )
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
