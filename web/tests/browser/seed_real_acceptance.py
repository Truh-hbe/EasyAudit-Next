"""Seed only bootstrap identities used by real browser acceptance."""

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

ORGANIZATION_ID = UUID("00000000-0000-4000-8000-000000000351")
ADMIN_USER_ID = UUID("00000000-0000-4000-8000-000000000352")
READY_USER_ID = UUID("00000000-0000-4000-8000-000000000353")
ADMIN_LOGIN_NAME = "browser-system-admin"
ADMIN_PASSWORD = "admin-password-000"
READY_LOGIN_NAME = "browser-ready-user"
READY_PASSWORD = "ready-password-000"
PASSWORD_HASH = PasswordHash.recommended()


def _credential(
    *,
    user_id: UUID,
    login_name: str,
    password: str,
) -> LocalCredentialRecord:
    return LocalCredentialRecord(
        user_id=user_id,
        organization_id=ORGANIZATION_ID,
        login_name=login_name,
        password_hash=PASSWORD_HASH.hash(password),
        password_changed_at=datetime.now(UTC),
        must_change_password=False,
    )


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session, session.begin():
            session.add(
                OrganizationRecord(
                    id=ORGANIZATION_ID,
                    name="M3.5.1 Browser Acceptance",
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
                ]
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
