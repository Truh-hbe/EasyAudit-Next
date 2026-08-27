from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import easyaudit_next.notifications.api as notification_api
from easyaudit_next.api.dependencies import (
    CurrentIdentity,
    get_database_session,
    require_business_identity,
)
from easyaudit_next.main import create_app
from easyaudit_next.platform.domain.ids import AuthSessionId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import AuthSession, PlatformRole, User

NOW = datetime(2026, 8, 27, 16, 0, tzinfo=UTC)


def _identity() -> CurrentIdentity:
    organization_id = OrganizationId(uuid4())
    user = User(
        id=UserId(uuid4()),
        organization_id=organization_id,
        display_name="Notification User",
        platform_role=PlatformRole.ORDINARY_USER,
    )
    return CurrentIdentity(
        auth_session=AuthSession(
            id=AuthSessionId(uuid4()),
            organization_id=organization_id,
            user_id=user.id,
            token_hash="a" * 64,
            expires_at=NOW + timedelta(hours=1),
            created_at=NOW,
        ),
        user=user,
    )


class _MissingNotificationService:
    def mark_read(
        self,
        organization_id: object,
        user_id: object,
        notification_id: object,
    ) -> None:
        raise LookupError("Notification not found")


def test_foreign_or_unknown_notification_id_is_non_disclosing_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    app.dependency_overrides[require_business_identity] = _identity
    app.dependency_overrides[get_database_session] = object
    monkeypatch.setattr(
        notification_api,
        "build_notification_service",
        lambda session: _MissingNotificationService(),
    )

    response = TestClient(app).post(
        f"/api/v1/me/notifications/{uuid4()}/read",
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Notification not found"}


def test_notification_inbox_rejects_unbounded_or_invalid_limits() -> None:
    app = create_app()
    app.dependency_overrides[require_business_identity] = _identity
    app.dependency_overrides[get_database_session] = object
    client = TestClient(app)

    assert client.get("/api/v1/me/notifications?limit=0").status_code == 422
    assert client.get("/api/v1/me/notifications?limit=101").status_code == 422
    assert client.get("/api/v1/me/notifications?offset=-1").status_code == 422
