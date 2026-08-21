from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from easyaudit_next.api.dependencies import (
    CurrentIdentity,
    get_authentication_service,
    get_current_identity,
    get_database_session,
)
from easyaudit_next.main import create_app
from easyaudit_next.platform.application.authentication import LoginResult
from easyaudit_next.platform.domain.ids import AuthSessionId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import AuthSession, PlatformRole, User

NOW = datetime(2026, 8, 21, tzinfo=UTC)


def identity(role: PlatformRole) -> CurrentIdentity:
    organization_id = OrganizationId(uuid4())
    user = User(
        id=UserId(uuid4()),
        organization_id=organization_id,
        display_name="Policy User",
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


def test_ordinary_user_cannot_access_admin_api() -> None:
    app = create_app()
    app.dependency_overrides[get_current_identity] = lambda: identity(PlatformRole.ORDINARY_USER)

    response = TestClient(app).get("/api/v1/admin/users")

    assert response.status_code == 403


class LoginAuthenticationStub:
    def login(self, login_name: str, password: str) -> LoginResult:
        current = identity(PlatformRole.SYSTEM_ADMIN)
        return LoginResult(
            token="browser-only-token",
            auth_session=current.auth_session,
            user=current.user,
        )


class SessionStub:
    def commit(self) -> None:
        pass


def test_login_cookie_uses_host_prefix_and_browser_protections() -> None:
    app = create_app()
    app.dependency_overrides[get_authentication_service] = LoginAuthenticationStub
    app.dependency_overrides[get_database_session] = SessionStub

    response = TestClient(app).post(
        "/api/v1/auth/login",
        json={"login_name": "admin", "password": "correct-horse-battery"},
    )

    cookie = response.headers["set-cookie"]
    assert response.status_code == 200
    assert cookie.startswith("__Host-easyaudit_session=")
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/" in cookie
