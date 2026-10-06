from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from easyaudit_next.api import router as router_module
from easyaudit_next.api.dependencies import (
    CurrentIdentity,
    get_current_identity,
    get_database_session,
)
from easyaudit_next.api.errors import DATABASE_CONFLICT_DETAIL
from easyaudit_next.main import create_app
from easyaudit_next.platform.application.authentication import LocalCredentialUnavailableError
from easyaudit_next.platform.application.password_policy import PasswordPolicyError
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


class _SessionStub:
    pass


class _ResetService:
    def __init__(self, result: User | BaseException) -> None:
        self._result = result

    def reset_local_credential(self, *_args: object, **_kwargs: object) -> User:
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


def _admin_client(monkeypatch: pytest.MonkeyPatch, result: User | BaseException) -> TestClient:
    app = create_app()
    monkeypatch.setattr(
        router_module,
        "_administration_service",
        lambda _session: _ResetService(result),
    )
    app.dependency_overrides[get_current_identity] = lambda: _identity(PlatformRole.SYSTEM_ADMIN)
    app.dependency_overrides[get_database_session] = lambda: _SessionStub()
    return TestClient(app)


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (LookupError("missing"), 404),
        (LocalCredentialUnavailableError("missing credential"), 409),
        (PasswordPolicyError("secret policy detail"), 422),
    ],
)
def test_credential_reset_error_statuses_are_frozen_and_safe(
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    expected_status: int,
) -> None:
    secret = "secret-policy-value-should-not-appear"
    response = _admin_client(monkeypatch, error).post(
        f"/api/v1/admin/users/{uuid4()}/credential-reset",
        json={"temporary_password": secret},
    )

    assert response.status_code == expected_status
    assert secret not in response.text


def test_credential_reset_success_is_user_response_for_inactive_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _identity(PlatformRole.ORDINARY_USER)
    inactive_target = replace(identity.user, is_active=False, display_name="Inactive target")
    response = _admin_client(monkeypatch, inactive_target).post(
        f"/api/v1/admin/users/{inactive_target.id}/credential-reset",
        json={"temporary_password": "secret-temporary-password-000"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(inactive_target.id),
        "organization_id": str(inactive_target.organization_id),
        "display_name": "Inactive target",
        "platform_role": "ordinary_user",
        "primary_department_id": None,
        "is_active": False,
    }
    assert "password" not in response.text.lower()


def test_m5_4_openapi_freezes_reset_and_scenario_status_shapes() -> None:
    schema = create_app().openapi()
    reset_operation = schema["paths"][
        "/api/v1/admin/users/{user_id}/credential-reset"
    ]["post"]
    reset_request_ref = reset_operation["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    reset_response_ref = reset_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    reset_request = schema["components"]["schemas"][reset_request_ref.rsplit("/", 1)[-1]]
    assert reset_request["properties"]["temporary_password"]["type"] == "string"
    assert "minLength" not in reset_request["properties"]["temporary_password"]
    assert reset_response_ref == "#/components/schemas/UserResponse"

    status_operation = schema["paths"]["/api/v1/admin/scenario-status"]["get"]
    status_ref = status_operation["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    status_schema = schema["components"]["schemas"][status_ref.rsplit("/", 1)[-1]]
    assert status_schema["properties"]["items"]["type"] == "array"
    item_ref = status_schema["properties"]["items"]["items"]["$ref"]
    item_schema = schema["components"]["schemas"][item_ref.rsplit("/", 1)[-1]]
    version_ref = item_schema["properties"]["versions"]["items"]["$ref"]
    version_schema = schema["components"]["schemas"][version_ref.rsplit("/", 1)[-1]]
    assert set(version_schema["properties"]) == {
        "scenario_version",
        "published_at",
        "registry_present",
        "ready",
    }


_LEAK_MARKERS = ("INSERT INTO", "SYNTHETIC_HASH_MARKER", "password_hash")


def _synthetic_integrity_error() -> IntegrityError:
    return IntegrityError(
        "INSERT INTO local_credentials (user_id, password_hash) "
        "VALUES (%(user_id)s, %(password_hash)s)",
        {"user_id": "u", "password_hash": "SYNTHETIC_HASH_MARKER"},
        Exception('duplicate key value violates unique constraint "uq_users_login_name"'),
    )


class _RaisingAdminService:
    def __getattr__(self, _name: str) -> object:
        def raise_integrity_error(*_args: object, **_kwargs: object) -> None:
            raise _synthetic_integrity_error()

        return raise_integrity_error


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        (
            "post",
            "/api/v1/admin/users",
            {
                "display_name": "Dup",
                "login_name": "dup",
                "initial_password": "a-valid-initial-password",
            },
        ),
        ("patch", f"/api/v1/admin/users/{uuid4()}", {"display_name": "x"}),
        ("post", "/api/v1/admin/departments", {"name": "Dup"}),
        ("patch", f"/api/v1/admin/departments/{uuid4()}", {"name": "x"}),
    ],
)
def test_admin_integrity_error_never_leaks_sql_or_parameters(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str, body: dict[str, object]
) -> None:
    app = create_app()
    monkeypatch.setattr(
        router_module, "_administration_service", lambda _session: _RaisingAdminService()
    )
    monkeypatch.setattr(
        router_module, "build_case_team_coordinator", lambda _session: _RaisingAdminService()
    )
    app.dependency_overrides[get_current_identity] = lambda: _identity(PlatformRole.SYSTEM_ADMIN)
    app.dependency_overrides[get_database_session] = lambda: _SessionStub()

    response = TestClient(app).request(method, path, json=body)

    assert response.status_code == 409
    assert response.json() == {"detail": DATABASE_CONFLICT_DETAIL}
    for marker in _LEAK_MARKERS:
        assert marker not in response.text
