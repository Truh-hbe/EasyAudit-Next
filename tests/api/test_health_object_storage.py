import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from easyaudit_next.api import health
from easyaudit_next.infrastructure import readiness
from easyaudit_next.infrastructure.readiness import DatabaseState
from easyaudit_next.infrastructure.readiness import (
    fetch_object_storage_failure as real_object_storage_probe,
)
from easyaudit_next.main import create_app
from easyaudit_next.platform.settings import Settings
from tests.conftest import SECRET_KEY, FakeS3, SilentTcpServer


def ready_client(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> TestClient:
    """Real object-storage probe, healthy database."""

    async def healthy_database(_: Settings) -> DatabaseState:
        return DatabaseState(True, ("head1",))

    monkeypatch.setattr(readiness, "fetch_object_storage_failure", real_object_storage_probe)
    monkeypatch.setattr(readiness, "fetch_database_state", healthy_database)
    monkeypatch.setattr(health, "get_settings", lambda: settings)
    app = create_app()
    app.state.expected_head = "head1"
    return TestClient(app)


def test_ready_is_ok_when_the_bucket_is_reachable(
    monkeypatch: pytest.MonkeyPatch, fake_s3: FakeS3
) -> None:
    response = ready_client(monkeypatch, fake_s3.settings()).get("/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"]["object_storage"] == "ok"


def test_ready_is_503_without_detail_when_the_store_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, fake_s3: FakeS3
) -> None:
    settings = fake_s3.settings(object_storage_endpoint="http://127.0.0.1:1")

    response = ready_client(monkeypatch, settings).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "fail",
        "checks": {
            "configuration": "ok",
            "database": "ok",
            "migrations": "ok",
            "object_storage": "fail",
        },
    }
    for leaked in (fake_s3.bucket, fake_s3.access_key, SECRET_KEY, "127.0.0.1", "refused"):
        assert leaked not in response.text


def test_ready_is_503_when_the_store_is_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    response = ready_client(monkeypatch, Settings()).get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["object_storage"] == "fail"


def test_ready_answers_503_within_the_deadline_for_hostile_stores(
    monkeypatch: pytest.MonkeyPatch, fake_s3: FakeS3, hostile_server: SilentTcpServer
) -> None:
    settings = fake_s3.settings(
        object_storage_endpoint=hostile_server.endpoint, readiness_timeout_seconds=1
    )
    client = ready_client(monkeypatch, settings)
    app = client.app

    async def scenario() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            return await http.get("/health/ready")

    started = time.perf_counter()
    response = asyncio.run(scenario())
    elapsed = time.perf_counter() - started  # includes the event loop's shutdown

    assert response.status_code == 503
    assert response.json()["checks"]["object_storage"] == "fail"
    assert elapsed < 1.8


def test_readiness_failure_log_has_no_credentials(
    monkeypatch: pytest.MonkeyPatch, fake_s3: FakeS3, log_output: object
) -> None:
    from tests.api.conftest import CapturedLogs

    assert isinstance(log_output, CapturedLogs)
    settings = fake_s3.settings(object_storage_endpoint="http://127.0.0.1:1")

    ready_client(monkeypatch, settings).get("/health/ready")

    text = "\n".join(
        line for line in log_output.text().splitlines() if '"logger": "easyaudit' in line
    )  # the fake S3 server's own access log is not ours
    assert "object_storage" in text
    for leaked in (SECRET_KEY, fake_s3.access_key, fake_s3.bucket, "127.0.0.1"):
        assert leaked not in text
