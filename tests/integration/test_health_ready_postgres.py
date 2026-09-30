import os

import pytest
from fastapi.testclient import TestClient

from easyaudit_next.main import create_app


def test_ready_is_ok_on_a_database_migrated_to_head() -> None:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")

    response = TestClient(create_app()).get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"configuration": "ok", "database": "ok", "migrations": "ok"},
    }
