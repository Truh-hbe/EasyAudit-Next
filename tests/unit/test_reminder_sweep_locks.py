from uuid import uuid4

from sqlalchemy.dialects import postgresql

from easyaudit_next.collaboration.reminder_sweep import organization_key_share_lock
from easyaudit_next.platform.domain.ids import OrganizationId


def test_organization_lock_compiles_to_for_key_share() -> None:
    sql = str(
        organization_key_share_lock(OrganizationId(uuid4())).compile(dialect=postgresql.dialect())
    )
    assert sql.rstrip().endswith("FOR KEY SHARE")
    assert "NO KEY UPDATE" not in sql
