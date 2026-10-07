"""Seed an isolated organization for the transfer-and-reopen browser journey (#86 B5).

Per scenario: an in-progress Case, a rectifying Finding owned by the login user, and a DONE
ActionItem whose only executor (the primary) has been deactivated.
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
    ActionAssigneeRecord,
    ActionItemRecord,
    CaseMemberRecord,
    FindingParticipantRecord,
    FindingRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)

ORGANIZATION_ID = UUID("00000000-0000-4000-8000-0000000003F0")
OWNER_ID = UUID("00000000-0000-4000-8000-0000000003F1")
OLD_PRIMARY_ID = UUID("00000000-0000-4000-8000-0000000003F2")
NEW_EXECUTOR_ID = UUID("00000000-0000-4000-8000-0000000003F3")

LOGIN_NAME = "browser-transfer-owner"
PASSWORD = "transfer-browser-password-000"
PASSWORD_HASH = PasswordHash.recommended()
BASE_TIME = datetime(2026, 10, 6, 1, 0, tzinfo=UTC)

# scenario key -> (offset, case data, finding data)
SCENARIOS = {
    "process_review": (
        0x10,
        {"area_code": "ASSY", "review_type": "routine"},
        {"issue_type": "control_gap", "project_category": "assembly"},
    ),
    "compliance_review": (
        0x20,
        {"standard_reference": "ISO 9001:2015", "scope_summary": "Assembly line"},
        {"criterion_reference": "8.5.1", "finding_type": "nonconformity"},
    ),
}


def ident(offset: int, index: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{0x3F00 + offset + index:012X}")


def action_id(scenario_key: str) -> UUID:
    return ident(SCENARIOS[scenario_key][0], 5)


def main() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        with Session(engine) as session, session.begin():
            session.add(OrganizationRecord(id=ORGANIZATION_ID, name="Transfer Browser Acceptance"))
            session.flush()
            session.add_all(
                [
                    UserRecord(
                        id=OWNER_ID,
                        organization_id=ORGANIZATION_ID,
                        display_name="Transfer Owner",
                        platform_role="ordinary_user",
                    ),
                    UserRecord(
                        id=OLD_PRIMARY_ID,
                        organization_id=ORGANIZATION_ID,
                        display_name="Departed Executor",
                        platform_role="ordinary_user",
                        is_active=False,
                    ),
                    UserRecord(
                        id=NEW_EXECUTOR_ID,
                        organization_id=ORGANIZATION_ID,
                        display_name="Successor Executor",
                        platform_role="ordinary_user",
                    ),
                ]
            )
            session.flush()
            session.add(
                LocalCredentialRecord(
                    user_id=OWNER_ID,
                    organization_id=ORGANIZATION_ID,
                    login_name=LOGIN_NAME,
                    password_hash=PASSWORD_HASH.hash(PASSWORD),
                    password_changed_at=BASE_TIME,
                    must_change_password=False,
                )
            )
            session.flush()
            for key, (offset, case_data, finding_data) in SCENARIOS.items():
                scenario_id, version_id = ident(offset, 0), ident(offset, 1)
                case_id, finding_id = ident(offset, 2), ident(offset, 3)
                session.add(
                    ScenarioRecord(
                        id=scenario_id, organization_id=ORGANIZATION_ID, key=key, name=key
                    )
                )
                session.flush()
                session.add(
                    ScenarioVersionRecord(
                        id=version_id,
                        scenario_id=scenario_id,
                        organization_id=ORGANIZATION_ID,
                        version=1,
                        published_at=BASE_TIME,
                    )
                )
                session.flush()
                session.add(
                    ReviewCaseRecord(
                        id=case_id,
                        organization_id=ORGANIZATION_ID,
                        plan_id=None,
                        scenario_version_id=version_id,
                        title=f"Transfer {key} Case",
                        lifecycle="in_progress",
                        planned_start_at=None,
                        planned_end_at=None,
                        started_at=BASE_TIME,
                        fieldwork_completed_at=None,
                        closed_at=None,
                        scenario_data_json=case_data,
                        created_by=OWNER_ID,
                        created_at=BASE_TIME,
                    )
                )
                session.flush()
                session.add(
                    CaseMemberRecord(
                        organization_id=ORGANIZATION_ID,
                        case_id=case_id,
                        user_id=OWNER_ID,
                        role_key="lead",
                        joined_at=BASE_TIME,
                    )
                )
                session.add(
                    FindingRecord(
                        id=finding_id,
                        organization_id=ORGANIZATION_ID,
                        case_id=case_id,
                        title=f"Transfer {key} Finding",
                        description=None,
                        severity="high",
                        lifecycle="rectifying",
                        raised_by=OWNER_ID,
                        raised_at=BASE_TIME,
                        scenario_data_json=finding_data,
                    )
                )
                session.flush()
                session.add(
                    FindingParticipantRecord(
                        id=ident(offset, 4),
                        organization_id=ORGANIZATION_ID,
                        finding_id=finding_id,
                        user_id=OWNER_ID,
                        department_id=None,
                        role_key="owner",
                        assigned_at=BASE_TIME,
                    )
                )
                session.add(
                    ActionItemRecord(
                        id=action_id(key),
                        organization_id=ORGANIZATION_ID,
                        finding_id=finding_id,
                        title=f"Transfer {key} Action",
                        lifecycle="done",
                        due_at=None,
                        completed_at=BASE_TIME,
                    )
                )
                session.flush()
                session.add(
                    ActionAssigneeRecord(
                        id=ident(offset, 6),
                        organization_id=ORGANIZATION_ID,
                        action_item_id=action_id(key),
                        user_id=OLD_PRIMARY_ID,
                        role="primary",
                        assigned_at=BASE_TIME,
                    )
                )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
