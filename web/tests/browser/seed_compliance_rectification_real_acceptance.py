"""Seed an isolated organization for the compliance_review nonconformity rectification journey.

Four ordinary users (lead, finding owner, action executor, reviewer), one department and the
published compliance_review@1 scenario. Cases, findings and actions are created through the UI.
"""

import os
from datetime import UTC, datetime
from uuid import UUID

from pwdlib import PasswordHash
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from easyaudit_next.platform.persistence.models import (
    DepartmentRecord,
    LocalCredentialRecord,
    OrganizationRecord,
    UserRecord,
)
from easyaudit_next.review_core.persistence.models import (
    ScenarioRecord,
    ScenarioVersionRecord,
)

ORGANIZATION_ID = UUID("00000000-0000-4000-8000-000000000400")
SCENARIO_ID = UUID("00000000-0000-4000-8000-000000000401")
SCENARIO_VERSION_ID = UUID("00000000-0000-4000-8000-000000000402")
DEPARTMENT_ID = UUID("00000000-0000-4000-8000-000000000403")

PASSWORD_HASH = PasswordHash.recommended()
BASE_TIME = datetime(2026, 10, 8, 1, 0, tzinfo=UTC)

# (user id, login name, password, display name); keep in sync with the browser spec.
USERS = [
    (
        UUID("00000000-0000-4000-8000-000000000410"),
        "rectify-lead",
        "rectify-lead-password-000",
        "Rectify Lead",
    ),
    (
        UUID("00000000-0000-4000-8000-000000000411"),
        "rectify-owner",
        "rectify-owner-password-000",
        "Rectify Owner",
    ),
    (
        UUID("00000000-0000-4000-8000-000000000412"),
        "rectify-executor",
        "rectify-executor-password-000",
        "Rectify Executor",
    ),
    (
        UUID("00000000-0000-4000-8000-000000000413"),
        "rectify-reviewer",
        "rectify-reviewer-password-000",
        "Rectify Reviewer",
    ),
]


def main() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        with Session(engine) as session, session.begin():
            # 幂等：--repeat-each 会重复执行 beforeAll，已有数据时直接复用。
            if session.get(OrganizationRecord, ORGANIZATION_ID) is not None:
                return
            session.add(
                OrganizationRecord(
                    id=ORGANIZATION_ID, name="Compliance Rectification Browser Acceptance"
                )
            )
            session.flush()
            session.add(
                DepartmentRecord(
                    id=DEPARTMENT_ID,
                    organization_id=ORGANIZATION_ID,
                    name="Rectify Quality Department",
                )
            )
            session.add_all(
                [
                    UserRecord(
                        id=user_id,
                        organization_id=ORGANIZATION_ID,
                        display_name=display_name,
                        platform_role="ordinary_user",
                    )
                    for user_id, _, _, display_name in USERS
                ]
            )
            session.add(
                ScenarioRecord(
                    id=SCENARIO_ID,
                    organization_id=ORGANIZATION_ID,
                    key="compliance_review",
                    name="Compliance Review",
                )
            )
            session.flush()
            session.add_all(
                [
                    LocalCredentialRecord(
                        user_id=user_id,
                        organization_id=ORGANIZATION_ID,
                        login_name=login_name,
                        password_hash=PASSWORD_HASH.hash(password),
                        password_changed_at=BASE_TIME,
                        must_change_password=False,
                    )
                    for user_id, login_name, password, _ in USERS
                ]
            )
            session.add(
                ScenarioVersionRecord(
                    id=SCENARIO_VERSION_ID,
                    scenario_id=SCENARIO_ID,
                    organization_id=ORGANIZATION_ID,
                    version=1,
                    published_at=BASE_TIME,
                )
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
