import pytest
from fastapi.testclient import TestClient

from easyaudit_next.api import health
from easyaudit_next.infrastructure import readiness
from easyaudit_next.infrastructure.readiness import DatabaseState
from easyaudit_next.main import create_app
from easyaudit_next.platform.settings import DEFAULT_DATABASE_URL, Settings

DSN_PASSWORD = "dsn-password-Q7"
UNREACHABLE = f"postgresql+psycopg://easyaudit:{DSN_PASSWORD}@127.0.0.1:1/easyaudit"


def client_with(
    monkeypatch: pytest.MonkeyPatch,
    *,
    settings: Settings | None = None,
    state: DatabaseState | None = None,
    head: str = "head1",
) -> TestClient:
    monkeypatch.setattr(health, "get_settings", lambda: settings or Settings())
    if state is not None:

        async def fake_state(_: Settings) -> DatabaseState:
            return state

        monkeypatch.setattr(readiness, "fetch_database_state", fake_state)
    app = create_app()
    app.state.expected_head = head
    return TestClient(app)


def assert_opaque(response_text: str) -> None:
    for leaked in (DSN_PASSWORD, "127.0.0.1", "head1", "postgresql", "Traceback", "refused"):
        assert leaked not in response_text


def test_live_is_ok_without_a_database(monkeypatch: pytest.MonkeyPatch) -> None:
    client = client_with(monkeypatch, settings=Settings(database_url=UNREACHABLE))

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_fails_with_opaque_body_when_database_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(database_url=UNREACHABLE, readiness_timeout_seconds=1)

    response = client_with(monkeypatch, settings=settings).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "fail",
        "checks": {"configuration": "ok", "database": "fail", "migrations": "fail"},
    }
    assert_opaque(response.text)


def test_ready_fails_on_revision_mismatch_without_revealing_revisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = client_with(monkeypatch, state=DatabaseState(True, ("stale-rev",)))

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {
        "configuration": "ok",
        "database": "ok",
        "migrations": "fail",
    }
    assert "stale-rev" not in response.text
    assert_opaque(response.text)


def test_ready_fails_when_database_was_never_migrated(monkeypatch: pytest.MonkeyPatch) -> None:
    client = client_with(monkeypatch, state=DatabaseState(True, ()))

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["migrations"] == "fail"


def test_ready_fails_when_required_configuration_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = client_with(
        monkeypatch, settings=Settings(database_url=""), state=DatabaseState(True, ("head1",))
    )

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["configuration"] == "fail"
    assert_opaque(response.text)


def test_ready_rejects_development_default_database_url_outside_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = client_with(
        monkeypatch,
        settings=Settings(app_env="production", database_url=DEFAULT_DATABASE_URL),
        state=DatabaseState(True, ("head1",)),
    )

    assert client.get("/health/ready").status_code == 503


def test_ready_is_ok_when_everything_checks_out(monkeypatch: pytest.MonkeyPatch) -> None:
    client = client_with(monkeypatch, state=DatabaseState(True, ("head1",)))

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"configuration": "ok", "database": "ok", "migrations": "ok"},
    }


def test_legacy_health_path_is_gone_and_not_under_api_prefix() -> None:
    client = TestClient(create_app())

    assert client.get("/health").status_code == 404
    assert client.get("/api/v1/health/live").status_code == 404
