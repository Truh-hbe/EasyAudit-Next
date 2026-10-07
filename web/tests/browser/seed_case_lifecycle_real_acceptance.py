"""Seed an isolated organization for case lifecycle command browser acceptance."""

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
    ScenarioRecord,
    ScenarioVersionRecord,
)

ORGANIZATION_ID = UUID("00000000-0000-4000-8000-0000000003E0")
USER_ID = UUID("00000000-0000-4000-8000-0000000003E1")
PROCESS_SCENARIO_ID = UUID("00000000-0000-4000-8000-0000000003E2")
PROCESS_VERSION_ID = UUID("00000000-0000-4000-8000-0000000003E3")
COMPLIANCE_SCENARIO_ID = UUID("00000000-0000-4000-8000-0000000003E4")
COMPLIANCE_VERSION_ID = UUID("00000000-0000-4000-8000-0000000003E5")

LOGIN_NAME = "browser-lifecycle-user"
PASSWORD = "lifecycle-browser-password-000"
PASSWORD_HASH = PasswordHash.recommended()
BASE_TIME = datetime(2026, 8, 30, 1, 0, tzinfo=UTC)


def main() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        with Session(engine) as session, session.begin():
            session.add(
                OrganizationRecord(
                    id=ORGANIZATION_ID,
                    name="Case Lifecycle Browser Acceptance",
                )
            )
            session.flush()
            session.add(
                UserRecord(
                    id=USER_ID,
                    organization_id=ORGANIZATION_ID,
                    display_name="Lifecycle Browser User",
                    platform_role="ordinary_user",
                )
            )
            session.flush()
            session.add(
                LocalCredentialRecord(
                    user_id=USER_ID,
                    organization_id=ORGANIZATION_ID,
                    login_name=LOGIN_NAME,
                    password_hash=PASSWORD_HASH.hash(PASSWORD),
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
                    ScenarioRecord(
                        id=COMPLIANCE_SCENARIO_ID,
                        organization_id=ORGANIZATION_ID,
                        key="compliance_review",
                        name="Compliance Review",
                    ),
                ]
            )
            session.flush()
            session.add_all(
                [
                    ScenarioVersionRecord(
                        id=PROCESS_VERSION_ID,
                        scenario_id=PROCESS_SCENARIO_ID,
                        organization_id=ORGANIZATION_ID,
                        version=1,
                        published_at=BASE_TIME,
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
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
