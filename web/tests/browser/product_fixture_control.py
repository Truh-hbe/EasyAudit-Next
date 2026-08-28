"""Test-only mutation controls for real browser acceptance fixtures."""

import os
import sys
from uuid import UUID

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from easyaudit_next.review_core.persistence.models import CaseMemberRecord

ORGANIZATION_ID = UUID("00000000-0000-4000-8000-000000000351")
VIEWER_USER_ID = UUID("00000000-0000-4000-8000-000000000354")
STALE_CASE_ID = UUID("00000000-0000-4000-8000-000000000375")


def revoke_viewer_case() -> None:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        with Session(engine) as session, session.begin():
            result = session.execute(
                delete(CaseMemberRecord).where(
                    CaseMemberRecord.organization_id == ORGANIZATION_ID,
                    CaseMemberRecord.case_id == STALE_CASE_ID,
                    CaseMemberRecord.user_id == VIEWER_USER_ID,
                    CaseMemberRecord.role_key == "observer",
                )
            )
            if result.rowcount != 1:
                raise RuntimeError(f"expected one stale CaseMember row, deleted {result.rowcount}")
    finally:
        engine.dispose()


def main() -> None:
    if sys.argv[1:] != ["revoke-viewer-case"]:
        raise SystemExit("usage: product_fixture_control.py revoke-viewer-case")
    revoke_viewer_case()


if __name__ == "__main__":
    main()
