import os
import time

import pytest
from fastapi.testclient import TestClient

from easyaudit_next.infrastructure.readiness import Failure
from easyaudit_next.main import create_app


@pytest.fixture(autouse=True)
def require_postgres() -> None:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")


def wait_until_db_settings_verified(client: TestClient) -> None:
    deadline = time.monotonic() + 10
    while getattr(client.app.state, "db_settings_failures", None) is None:
        assert time.monotonic() < deadline, "db settings were never verified"
        time.sleep(0.05)


def test_ready_is_ok_on_a_database_migrated_to_head() -> None:
    with TestClient(create_app()) as client:  # runs lifespan: loads the expected head
        wait_until_db_settings_verified(client)
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {
            "configuration": "ok",
            "database": "ok",
            "migrations": "ok",
            "db_settings": "ok",
        },
    }


def test_ready_fails_when_the_server_enforces_different_timeouts() -> None:
    with TestClient(create_app()) as client:
        wait_until_db_settings_verified(client)
        client.app.state.db_settings_failures = (  # type: ignore[attr-defined]
            Failure("db_settings", "mismatch", {"setting": "statement_timeout"}),
        )
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["db_settings"] == "fail"


def test_ready_fails_when_the_expected_head_differs() -> None:
    with TestClient(create_app()) as client:
        client.app.state.expected_head = "not-the-real-head"  # type: ignore[attr-defined]
        wait_until_db_settings_verified(client)
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {
        "configuration": "ok",
        "database": "ok",
        "migrations": "fail",
        "db_settings": "ok",
    }
    assert "not-the-real-head" not in response.text
