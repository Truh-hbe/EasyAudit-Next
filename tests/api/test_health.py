import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import StaticPool

from easyaudit_next.api import health
from easyaudit_next.infrastructure.readiness import get_readiness_engine
from easyaudit_next.main import create_app
from easyaudit_next.platform.settings import Settings

DSN_PASSWORD = "dsn-password-Q7"
UNREACHABLE = f"postgresql+psycopg://easyaudit:{DSN_PASSWORD}@127.0.0.1:1/easyaudit"


def unreachable_engine() -> Engine:
    return create_engine(UNREACHABLE, connect_args={"connect_timeout": 1})


def sqlite_engine(revision: str | None) -> Engine:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    if revision is not None:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
            connection.execute(text("INSERT INTO alembic_version VALUES (:v)"), {"v": revision})
    return engine


def client_with(engine: Engine, monkeypatch: pytest.MonkeyPatch, head: str = "head1") -> TestClient:
    app = create_app()
    app.dependency_overrides[get_readiness_engine] = lambda: engine
    monkeypatch.setattr(health, "get_expected_head", lambda: head)
    return TestClient(app)


def assert_opaque(response_text: str) -> None:
    for leaked in (DSN_PASSWORD, "127.0.0.1", "head1", "postgresql", "Traceback", "refused"):
        assert leaked not in response_text


def test_live_is_ok_without_a_database(monkeypatch: pytest.MonkeyPatch) -> None:
    client = client_with(unreachable_engine(), monkeypatch)

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_fails_with_opaque_body_when_database_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = client_with(unreachable_engine(), monkeypatch).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "fail",
        "checks": {"configuration": "ok", "database": "fail", "migrations": "fail"},
    }
    assert_opaque(response.text)


def test_ready_fails_on_revision_mismatch_without_revealing_revisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = client_with(sqlite_engine("stale-rev"), monkeypatch).get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {
        "configuration": "ok",
        "database": "ok",
        "migrations": "fail",
    }
    assert "stale-rev" not in response.text
    assert_opaque(response.text)


def test_ready_fails_when_database_was_never_migrated(monkeypatch: pytest.MonkeyPatch) -> None:
    response = client_with(sqlite_engine(None), monkeypatch).get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["migrations"] == "fail"


def test_ready_fails_when_required_configuration_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = client_with(sqlite_engine("head1"), monkeypatch)
    monkeypatch.setattr(health, "get_settings", lambda: Settings(database_url=""))

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["configuration"] == "fail"
    assert_opaque(response.text)


def test_ready_rejects_development_default_database_url_outside_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = client_with(sqlite_engine("head1"), monkeypatch)
    monkeypatch.setattr(health, "get_settings", lambda: Settings(app_env="production"))

    assert client.get("/health/ready").status_code == 503


def test_ready_is_ok_when_everything_checks_out(monkeypatch: pytest.MonkeyPatch) -> None:
    response = client_with(sqlite_engine("head1"), monkeypatch).get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"configuration": "ok", "database": "ok", "migrations": "ok"},
    }


def test_legacy_health_path_is_gone_and_not_under_api_prefix() -> None:
    client = TestClient(create_app())

    assert client.get("/health").status_code == 404
    assert client.get("/api/v1/health/live").status_code == 404
