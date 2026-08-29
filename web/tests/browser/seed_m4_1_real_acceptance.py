"""Seed deterministic M4.1 compliance facts for real browser acceptance."""

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
    FindingRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)

ORGANIZATION_ID = UUID("00000000-0000-4000-8000-000000000351")
COMPLIANCE_USER_ID = UUID("00000000-0000-4000-8000-000000000359")
COMPLIANCE_SCENARIO_ID = UUID("00000000-0000-4000-8000-000000000362")
COMPLIANCE_SCENARIO_VERSION_ID = UUID("00000000-0000-4000-8000-000000000363")
COMPLIANCE_CASE_ID = UUID("00000000-0000-4000-8000-000000000377")
COMPLIANCE_FINDING_ID = UUID("00000000-0000-4000-8000-000000000386")

LOGIN_NAME = "browser-compliance-lead"
PASSWORD = "compliance-password-000"
PASSWORD_HASH = PasswordHash.recommended()
BASE_TIME = datetime(2026, 8, 29, 3, 30, tzinfo=UTC)


def main() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        with Session(engine) as session, session.begin():
            organization = session.get(OrganizationRecord, ORGANIZATION_ID)
            if organization is None:
                raise RuntimeError("base real-browser Organization must be seeded first")
            if session.get(UserRecord, COMPLIANCE_USER_ID) is not None:
                raise RuntimeError("M4.1 real-browser fixture requires a clean database")

            session.add(
                UserRecord(
                    id=COMPLIANCE_USER_ID,
                    organization_id=ORGANIZATION_ID,
                    display_name="M4.1 Compliance Lead",
                    platform_role="ordinary_user",
                )
            )
            session.flush()
            session.add(
                LocalCredentialRecord(
                    user_id=COMPLIANCE_USER_ID,
                    organization_id=ORGANIZATION_ID,
                    login_name=LOGIN_NAME,
                    password_hash=PASSWORD_HASH.hash(PASSWORD),
                    password_changed_at=BASE_TIME,
                    must_change_password=False,
                )
            )
            session.flush()

            session.add(
                ScenarioRecord(
                    id=COMPLIANCE_SCENARIO_ID,
                    organization_id=ORGANIZATION_ID,
                    key="compliance_review",
                    name="Compliance Review",
                )
            )
            session.flush()
            session.add(
                ScenarioVersionRecord(
                    id=COMPLIANCE_SCENARIO_VERSION_ID,
                    scenario_id=COMPLIANCE_SCENARIO_ID,
                    organization_id=ORGANIZATION_ID,
                    version=1,
                    published_at=BASE_TIME,
                )
            )
            session.flush()

            session.add(
                ReviewCaseRecord(
                    id=COMPLIANCE_CASE_ID,
                    organization_id=ORGANIZATION_ID,
                    plan_id=None,
                    scenario_version_id=COMPLIANCE_SCENARIO_VERSION_ID,
                    title="M4.1 Compliance Browser Case",
                    lifecycle="in_progress",
                    planned_start_at=datetime(2026, 8, 29, tzinfo=UTC),
                    planned_end_at=datetime(2026, 9, 30, tzinfo=UTC),
                    started_at=BASE_TIME,
                    fieldwork_completed_at=None,
                    closed_at=None,
                    scenario_data_json={
                        "standard_reference": "ISO 9001:2015",
                        "scope_summary": "Assembly control and document retention",
                    },
                    created_by=COMPLIANCE_USER_ID,
                    created_at=BASE_TIME,
                )
            )
            session.flush()
            session.add_all(
                [
                    CaseMemberRecord(
                        organization_id=ORGANIZATION_ID,
                        case_id=COMPLIANCE_CASE_ID,
                        user_id=COMPLIANCE_USER_ID,
                        role_key="lead",
                        joined_at=BASE_TIME,
                    ),
                    CaseMemberRecord(
                        organization_id=ORGANIZATION_ID,
                        case_id=COMPLIANCE_CASE_ID,
                        user_id=COMPLIANCE_USER_ID,
                        role_key="reviewer",
                        joined_at=BASE_TIME,
                    ),
                ]
            )
            session.flush()
            session.add(
                FindingRecord(
                    id=COMPLIANCE_FINDING_ID,
                    organization_id=ORGANIZATION_ID,
                    case_id=COMPLIANCE_CASE_ID,
                    title="M4.1 Compliance Observation",
                    description=(
                        "Observation closes directly without synthetic rectification facts."
                    ),
                    severity="low",
                    lifecycle="open",
                    raised_by=COMPLIANCE_USER_ID,
                    raised_at=BASE_TIME,
                    scenario_data_json={
                        "criterion_reference": "7.5.3",
                        "finding_type": "observation",
                    },
                )
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
