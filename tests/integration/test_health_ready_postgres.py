import os

import pytest
from fastapi.testclient import TestClient

from easyaudit_next.api import health
from easyaudit_next.main import create_app
from easyaudit_next.platform.settings import get_settings
from tests.conftest import FakeS3


@pytest.fixture(autouse=True)
def require_postgres() -> None:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")


@pytest.fixture(autouse=True)
def with_object_storage(monkeypatch: pytest.MonkeyPatch, fake_s3: FakeS3) -> None:
    settings = fake_s3.settings(database_url=get_settings().database_url)
    monkeypatch.setattr(health, "get_settings", lambda: settings)


def test_ready_is_ok_on_a_database_migrated_to_head() -> None:
    with TestClient(create_app()) as client:  # runs lifespan: loads the expected head
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {
            "configuration": "ok",
            "database": "ok",
            "migrations": "ok",
            "object_storage": "ok",
        },
    }


def test_ready_fails_when_the_expected_head_differs() -> None:
    with TestClient(create_app()) as client:
        client.app.state.expected_head = "not-the-real-head"  # type: ignore[attr-defined]
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {
        "configuration": "ok",
        "database": "ok",
        "migrations": "fail",
        "object_storage": "ok",
    }
    assert "not-the-real-head" not in response.text
