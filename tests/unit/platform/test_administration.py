from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest

from easyaudit_next.platform.application.administration import (
    LastSystemAdminError,
    PlatformAdministrationService,
)
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.domain.models import PlatformRole, User

NOW = datetime(2026, 8, 21, tzinfo=UTC)


def system_admin() -> User:
    return User(
        id=UserId(uuid4()),
        organization_id=OrganizationId(uuid4()),
        display_name="Only Administrator",
        platform_role=PlatformRole.SYSTEM_ADMIN,
    )


@pytest.mark.parametrize(
    ("platform_role", "is_active"),
    [
        (PlatformRole.ORDINARY_USER, None),
        (None, False),
    ],
)
def test_last_active_system_admin_cannot_be_demoted_or_disabled(
    platform_role: PlatformRole | None,
    is_active: bool | None,
) -> None:
    actor = system_admin()
    users = Mock()
    users.get.return_value = actor
    users.count_active_system_admins.return_value = 1
    service = PlatformAdministrationService(
        Mock(),
        Mock(),
        users,
        Mock(),
        Mock(),
        Mock(),
    )

    with pytest.raises(LastSystemAdminError):
        service.update_user(
            actor,
            actor.id,
            platform_role=platform_role,
            is_active=is_active,
            now=NOW,
        )

    users.update.assert_not_called()


def test_admin_can_be_demoted_when_another_active_admin_exists() -> None:
    actor = system_admin()
    users = Mock()
    users.get.return_value = actor
    users.count_active_system_admins.return_value = 2
    audit = Mock()
    service = PlatformAdministrationService(
        Mock(),
        Mock(),
        users,
        Mock(),
        Mock(),
        audit,
    )

    updated = service.update_user(
        actor,
        actor.id,
        platform_role=PlatformRole.ORDINARY_USER,
        now=NOW,
    )

    assert updated.platform_role is PlatformRole.ORDINARY_USER
    users.update.assert_called_once_with(updated)
    audit.add.assert_called_once()
