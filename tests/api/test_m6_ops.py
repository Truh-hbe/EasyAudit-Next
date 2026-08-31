from __future__ import annotations

import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import easyaudit_next.infrastructure.database as database_module
from easyaudit_next.api.operational import operational_router
from easyaudit_next.api.dependencies import get_application_engine
from easyaudit_next.operations.logging import SafeJsonFormatter
from easyaudit_next.operations.middleware import (
    LoginAdmissionMiddleware,
    RequestObservabilityMiddleware,
    accepted_request_id,
)
from easyaudit_next.operations.rate_limit import LoginRateLimiter
from easyaudit_next.platform.login_identity import normalize_login_name
from easyaudit_next.platform.settings import Settings


def test_request_id_validation_preserves_only_reviewed_values() -> None:
    assert accepted_request_id("client-123._:ok") == "client-123._:ok"
    for invalid in (None, "", "space value", "x" * 65, "bad/query"):
        generated = accepted_request_id(invalid)
        assert generated != invalid
        assert len(generated) == 32


def test_liveness_never_resolves_database_dependency() -> None:
    app = FastAPI()
    app.include_router(operational_router)

    def forbidden_engine() -> object:
        raise AssertionError("liveness must not resolve the database engine")

    app.dependency_overrides[get_application_engine] = forbidden_engine
    response = TestClient(app).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_request_observability_returns_request_id_for_success_404_and_500() -> None:
    app = FastAPI()
    app.add_middleware(RequestObservabilityMiddleware)

    @app.get("/ok")
    def ok() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/explode")
    def explode() -> None:
        raise RuntimeError("SECRET_EXCEPTION_SENTINEL")

    client = TestClient(app, raise_server_exceptions=False)
    valid = client.get("/ok", headers={"X-Request-ID": "accepted-id"})
    assert valid.status_code == 200
    assert valid.headers["X-Request-ID"] == "accepted-id"

    missing = client.get("/does-not-exist")
    assert missing.status_code == 404
    assert missing.headers["X-Request-ID"]

    failed = client.get("/explode")
    assert failed.status_code == 500
    assert failed.headers["X-Request-ID"]
    assert failed.json() == {"detail": "Internal server error"}
    assert "SECRET_EXCEPTION_SENTINEL" not in failed.text


def test_safe_json_formatter_drops_arbitrary_message_and_exception_text() -> None:
    formatter = SafeJsonFormatter()
    try:
        raise RuntimeError("SECRET_LOG_SENTINEL")
    except RuntimeError:
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="SECRET_MESSAGE_SENTINEL",
            args=(),
            exc_info=__import__("sys").exc_info(),
        )
    rendered = formatter.format(record)
    payload = json.loads(rendered)
    assert payload["error_class"] == "RuntimeError"
    assert "SECRET_LOG_SENTINEL" not in rendered
    assert "SECRET_MESSAGE_SENTINEL" not in rendered


def test_login_normalization_is_shared_and_aliases_exhaust_one_bucket() -> None:
    assert {normalize_login_name(value) for value in ("alice", "Alice", "ALICE", " alice ")} == {
        "alice"
    }
    limiter = LoginRateLimiter(
        global_capacity=20,
        global_refill_per_second=0.001,
        per_key_capacity=1,
        per_key_refill_per_second=0.001,
        fingerprint_key=b"fixed-test-key",
    )
    assert limiter.admit("Alice", "10.0.0.1").allowed
    assert not limiter.admit(" alice ", "10.0.0.1").allowed


def test_two_budget_denial_consumes_neither_side() -> None:
    now = [0.0]
    limiter = LoginRateLimiter(
        clock=lambda: now[0],
        global_capacity=1,
        global_refill_per_second=1,
        per_key_capacity=1,
        per_key_refill_per_second=0.01,
        fingerprint_key=b"atomic-test-key",
    )
    assert limiter.admit("first", "peer").allowed
    assert not limiter.admit("second", "peer").allowed

    # A denied global bucket must not consume the second per-key bucket. Refill
    # only the global token and the second identity must still be admitted.
    now[0] = 1.0
    assert limiter.admit("second", "peer").allowed


def test_denied_per_key_does_not_drain_global_bucket() -> None:
    limiter = LoginRateLimiter(
        global_capacity=10,
        global_refill_per_second=0.001,
        per_key_capacity=1,
        per_key_refill_per_second=0.001,
        fingerprint_key=b"per-key-test",
    )
    assert limiter.admit("alice", "peer").allowed
    after_first = limiter.global_tokens
    for _ in range(5):
        assert not limiter.admit("ALICE", "peer").allowed
    assert limiter.global_tokens == pytest.approx(after_first)


def test_limiter_concurrency_never_over_admits_final_token() -> None:
    limiter = LoginRateLimiter(
        global_capacity=1,
        global_refill_per_second=0.000001,
        per_key_capacity=1,
        per_key_refill_per_second=0.000001,
        fingerprint_key=b"concurrency-test",
    )
    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions = list(pool.map(lambda _: limiter.admit("alice", "peer").allowed, range(8)))
    assert sum(decisions) == 1


def test_limiter_state_is_memory_bounded() -> None:
    limiter = LoginRateLimiter(
        global_capacity=100,
        global_refill_per_second=1,
        per_key_capacity=2,
        per_key_refill_per_second=1,
        max_entries=3,
        fingerprint_key=b"bounded-state-test",
    )
    for index in range(10):
        limiter.admit(f"user-{index}", f"peer-{index}")
    assert limiter.entry_count <= 3


def test_login_middleware_ignores_untrusted_forwarding_headers_and_stops_downstream() -> None:
    calls: list[str] = []
    limiter = LoginRateLimiter(
        global_capacity=10,
        global_refill_per_second=0.001,
        per_key_capacity=1,
        per_key_refill_per_second=0.001,
        fingerprint_key=b"middleware-test",
    )
    app = FastAPI()
    app.add_middleware(LoginAdmissionMiddleware, limiter=limiter)

    @app.post("/api/v1/auth/login")
    def login() -> dict[str, bool]:
        calls.append("called")
        return {"ok": True}

    client = TestClient(app)
    first = client.post(
        "/api/v1/auth/login",
        json={"login_name": "Alice", "password": "SECRET_PASSWORD_SENTINEL"},
        headers={"X-Forwarded-For": "203.0.113.1"},
    )
    second = client.post(
        "/api/v1/auth/login",
        json={"login_name": " alice ", "password": "SECRET_PASSWORD_SENTINEL"},
        headers={"X-Forwarded-For": "198.51.100.2"},
    )
    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) >= 1
    assert calls == ["called"]


def test_database_engine_configuration_applies_all_reviewed_budgets(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_create_engine(url: str, **kwargs: object) -> object:
        captured["url"] = url
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(database_module, "create_engine", fake_create_engine)
    settings = Settings(
        database_url="postgresql+psycopg://user:password@db.example/easyaudit",
        database_pool_size=7,
        database_pool_timeout_seconds=6,
        database_connect_timeout_seconds=4,
        database_statement_timeout_ms=12_000,
        database_lock_timeout_ms=2_000,
        database_idle_transaction_timeout_ms=55_000,
    )
    assert database_module.create_database_engine(settings) is sentinel
    assert captured["pool_pre_ping"] is True
    assert captured["pool_size"] == 7
    assert captured["max_overflow"] == 0
    assert captured["pool_timeout"] == 6
    connect_args = captured["connect_args"]
    assert isinstance(connect_args, dict)
    assert connect_args["connect_timeout"] == 4
    options = str(connect_args["options"])
    assert "statement_timeout=12000" in options
    assert "lock_timeout=2000" in options
    assert "idle_in_transaction_session_timeout=55000" in options


def test_database_budget_validation_rejects_unbounded_or_inverted_values() -> None:
    with pytest.raises(ValidationError):
        Settings(database_pool_size=0)
    with pytest.raises(ValidationError):
        Settings(database_lock_timeout_ms=15_000, database_statement_timeout_ms=15_000)


def test_operational_dependency_direction_is_enforced_by_source() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "easyaudit_next"
    forbidden_tokens = ("easyaudit_next.operations", "fastapi", "starlette")
    for area in (root / "platform" / "application", root / "platform" / "domain"):
        for path in area.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                assert token not in text, f"{path} imports forbidden operational/HTTP concern {token}"
    for area in (root / "review_core", root / "scenarios"):
        for path in area.rglob("*.py"):
            assert "easyaudit_next.operations" not in path.read_text(encoding="utf-8")
