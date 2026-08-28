"""Seed the isolated PostgreSQL database used by real browser acceptance."""

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
USER_ID = UUID("00000000-0000-4000-8000-000000000352")
LOGIN_NAME = "browser-credential-user"
INITIAL_PASSWORD = "initial-password-000"


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
            session.add(
                UserRecord(
                    id=USER_ID,
                    organization_id=ORGANIZATION_ID,
                    display_name="Browser Credential User",
                    platform_role="ordinary_user",
                )
            )
            session.flush()
            session.add(
                LocalCredentialRecord(
                    user_id=USER_ID,
                    organization_id=ORGANIZATION_ID,
                    login_name=LOGIN_NAME,
                    password_hash=PasswordHash.recommended().hash(INITIAL_PASSWORD),
                    password_changed_at=datetime.now(UTC),
                    must_change_password=True,
                )
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
