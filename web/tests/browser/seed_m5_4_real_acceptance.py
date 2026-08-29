"""Seed an isolated organization for M5.4 administration acceptance."""

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

ORGANIZATION_ID = UUID("00000000-0000-4000-8000-0000000003C0")
ADMIN_USER_ID = UUID("00000000-0000-4000-8000-0000000003C1")
MANAGER_USER_ID = UUID("00000000-0000-4000-8000-0000000003C2")
PROCESS_SCENARIO_ID = UUID("00000000-0000-4000-8000-0000000003C3")
PROCESS_VERSION_ID = UUID("00000000-0000-4000-8000-0000000003C4")
COMPLIANCE_SCENARIO_ID = UUID("00000000-0000-4000-8000-0000000003C5")
COMPLIANCE_VERSION_ID = UUID("00000000-0000-4000-8000-0000000003C6")
CASE_ID = UUID("00000000-0000-4000-8000-0000000003C7")

ADMIN_LOGIN_NAME = "browser-m5-4-admin"
ADMIN_PASSWORD = "m5-4-browser-admin-password-000"
MANAGER_LOGIN_NAME = "browser-m5-4-manager"
MANAGER_PASSWORD = "m5-4-browser-manager-password-000"
PASSWORD_HASH = PasswordHash.recommended()
BASE_TIME = datetime(2026, 8, 30, 6, 0, tzinfo=UTC)


def main() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        with Session(engine) as session, session.begin():
            session.add(
                OrganizationRecord(id=ORGANIZATION_ID, name="M5.4 Browser Acceptance")
            )
            session.flush()
            session.add_all(
                [
                    UserRecord(
                        id=ADMIN_USER_ID,
                        organization_id=ORGANIZATION_ID,
                        display_name="M5.4 Browser System Admin",
                        platform_role="system_admin",
                    ),
                    UserRecord(
                        id=MANAGER_USER_ID,
                        organization_id=ORGANIZATION_ID,
                        display_name="M5.4 Browser Case Manager",
                        platform_role="ordinary_user",
                    ),
                ]
            )
            session.flush()
            session.add_all(
                [
                    LocalCredentialRecord(
                        user_id=ADMIN_USER_ID,
                        organization_id=ORGANIZATION_ID,
                        login_name=ADMIN_LOGIN_NAME,
                        password_hash=PASSWORD_HASH.hash(ADMIN_PASSWORD),
                        password_changed_at=BASE_TIME,
                        must_change_password=False,
                    ),
                    LocalCredentialRecord(
                        user_id=MANAGER_USER_ID,
                        organization_id=ORGANIZATION_ID,
                        login_name=MANAGER_LOGIN_NAME,
                        password_hash=PASSWORD_HASH.hash(MANAGER_PASSWORD),
                        password_changed_at=BASE_TIME,
                        must_change_password=False,
                    ),
                ]
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
                ]
            )
            session.flush()
            session.add(
                ReviewCaseRecord(
                    id=CASE_ID,
                    organization_id=ORGANIZATION_ID,
                    plan_id=None,
                    scenario_version_id=PROCESS_VERSION_ID,
                    title="M5.4 Browser Manager Case",
                    lifecycle="in_progress",
                    planned_start_at=BASE_TIME,
                    planned_end_at=datetime(2026, 9, 30, tzinfo=UTC),
                    started_at=BASE_TIME,
                    fieldwork_completed_at=None,
                    closed_at=None,
                    scenario_data_json={"area_code": "M54", "review_type": "pilot"},
                    created_by=MANAGER_USER_ID,
                    created_at=BASE_TIME,
                )
            )
            session.flush()
            session.add(
                CaseMemberRecord(
                    organization_id=ORGANIZATION_ID,
                    case_id=CASE_ID,
                    user_id=MANAGER_USER_ID,
                    role_key="lead",
                    joined_at=BASE_TIME,
                )
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
