import os

import pytest
from fastapi.testclient import TestClient

from easyaudit_next.api import health
from easyaudit_next.main import create_app


@pytest.fixture(autouse=True)
def require_postgres() -> None:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")


def test_ready_is_ok_on_a_database_migrated_to_head() -> None:
    response = TestClient(create_app()).get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"configuration": "ok", "database": "ok", "migrations": "ok"},
    }


def test_ready_fails_when_the_expected_head_differs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "get_expected_head", lambda: "not-the-real-head")

    response = TestClient(create_app()).get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {
        "configuration": "ok",
        "database": "ok",
        "migrations": "fail",
    }
    assert "not-the-real-head" not in response.text
