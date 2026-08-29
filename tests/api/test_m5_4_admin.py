from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from easyaudit_next.api.dependencies import CurrentIdentity, get_current_identity
from easyaudit_next.main import create_app
from easyaudit_next.platform.domain.ids import AuthSessionId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import AuthSession, PlatformRole, User

NOW = datetime(2026, 8, 30, tzinfo=UTC)


def _identity(role: PlatformRole) -> CurrentIdentity:
    organization_id = OrganizationId(uuid4())
    user = User(
        id=UserId(uuid4()),
        organization_id=organization_id,
        display_name="M5.4 policy user",
        platform_role=role,
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


def test_ordinary_user_cannot_read_admin_status_or_reset_target() -> None:
    app = create_app()
    app.dependency_overrides[get_current_identity] = lambda: _identity(PlatformRole.ORDINARY_USER)
    client = TestClient(app)

    assert client.get("/api/v1/admin/scenario-status").status_code == 403
    assert (
        client.post(
            f"/api/v1/admin/users/{uuid4()}/credential-reset",
            json={"temporary_password": "a-valid-temporary-password"},
        ).status_code
        == 403
    )


def test_unauthenticated_credential_reset_is_rejected_before_target_lookup() -> None:
    client = TestClient(create_app())

    response = client.post(
        f"/api/v1/admin/users/{uuid4()}/credential-reset",
        json={"temporary_password": "a-valid-temporary-password"},
    )

    assert response.status_code == 401
