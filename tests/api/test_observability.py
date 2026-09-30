import io
import json
import logging
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from easyaudit_next.api.dependencies import (
    AuthenticatedIdentity,
    get_authentication_service,
    get_database_session,
)
from easyaudit_next.infrastructure import observability
from easyaudit_next.infrastructure.observability import JsonFormatter, build_log_config
from easyaudit_next.main import create_app
from easyaudit_next.platform.domain.models import PlatformRole
from tests.api.test_auth_policy import identity

PASSWORD = "Zx9-distinctive-Password-7731"
SESSION_TOKEN = "session-token-distinctive-5528"
SECRET_QUERY = "needle-query-value-4419"
SECRET_EXCEPTION_TEXT = "SELECT secret FROM t WHERE ssn = 'sensitive-parameter-8842'"

REQUIRED_ACCESS_FIELDS = {
    "timestamp",
    "level",
    "request_id",
    "method",
    "route",
    "status_code",
    "latency_ms",
    "organization_id",
    "actor_user_id",
}


class UnsafeError(Exception):
    pass


class SafeError(Exception):
    pass


class AuthStub:
    def __init__(self) -> None:
        self.current = identity(PlatformRole.ORDINARY_USER)

    def login(self, login_name: str, password: str) -> Any:
        from easyaudit_next.platform.application.authentication import LoginResult

        return LoginResult(
            token=SESSION_TOKEN,
            auth_session=self.current.auth_session,
            user=self.current.user,
        )

    def authenticate(self, token: str) -> Any:
        assert token == SESSION_TOKEN
        return self.current.auth_session, self.current.user

    def touch(self, auth_session: object) -> None:
        pass


class SessionStub:
    def commit(self) -> None:
        pass


@pytest.fixture
def log_output() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("easyaudit")
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    yield stream
    logger.removeHandler(handler)
    logger.setLevel(previous_level)


def lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def access_lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [line for line in lines(stream) if line["logger"] == "easyaudit.access"]


def build_app(auth: AuthStub) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_authentication_service] = lambda: auth
    app.dependency_overrides[get_database_session] = SessionStub

    @app.get("/test/cases/{case_id}")
    def show_case(case_id: str, who: AuthenticatedIdentity) -> dict[str, str]:
        return {"case_id": case_id}

    @app.get("/test/boom")
    def boom() -> None:
        raise UnsafeError(SECRET_EXCEPTION_TEXT)

    @app.get("/test/safe-boom")
    def safe_boom() -> None:
        raise SafeError("case is in a state that cannot be closed")

    return app


def test_every_response_has_a_server_generated_request_id(log_output: io.StringIO) -> None:
    client = TestClient(build_app(AuthStub()))
    client_supplied = "attacker-controlled\nvalue"

    ok = client.get("/health/live", headers={"X-Request-ID": client_supplied})
    missing = client.get("/no-such-route")

    for response in (ok, missing):
        assert (
            str(UUID(response.headers["x-request-id"], version=4))
            == (response.headers["x-request-id"])
        )
    assert ok.headers["x-request-id"] != client_supplied
    assert ok.headers["x-request-id"] != missing.headers["x-request-id"]
    assert client_supplied not in log_output.getvalue()


def test_access_log_has_required_fields_and_matches_response_header(
    log_output: io.StringIO,
) -> None:
    auth = AuthStub()
    client = TestClient(build_app(auth))

    response = client.get(
        f"/test/cases/abc?token={SECRET_QUERY}", cookies={"__Host-easyaudit_session": SESSION_TOKEN}
    )

    [entry] = access_lines(log_output)
    assert REQUIRED_ACCESS_FIELDS <= entry.keys()
    assert entry["request_id"] == response.headers["x-request-id"]
    assert entry["route"] == "/test/cases/{case_id}"
    assert entry["method"] == "GET"
    assert entry["status_code"] == 200
    assert entry["organization_id"] == str(auth.current.user.organization_id)
    assert entry["actor_user_id"] == str(auth.current.user.id)
    assert entry["timestamp"].endswith("+00:00")
    assert entry["latency_ms"] >= 0


def test_unauthenticated_and_unmatched_requests_log_null_actor_and_route(
    log_output: io.StringIO,
) -> None:
    client = TestClient(build_app(AuthStub()))

    client.get("/test/cases/abc")
    client.get("/definitely/not/a/route")

    unauthenticated, unmatched = access_lines(log_output)
    assert unauthenticated["status_code"] == 401
    assert unauthenticated["route"] == "/test/cases/{case_id}"
    assert unauthenticated["organization_id"] is None
    assert unauthenticated["actor_user_id"] is None
    assert unmatched["status_code"] == 404
    assert unmatched["route"] is None


def test_login_then_authenticated_query_does_not_leak_secrets(log_output: io.StringIO) -> None:
    client = TestClient(build_app(AuthStub()))

    login = client.post(
        "/api/v1/auth/login",
        json={"login_name": "admin", "password": PASSWORD},
        headers={"Authorization": "Bearer bearer-secret-1187"},
    )
    assert login.status_code == 200
    client.get(
        f"/test/cases/abc?token={SECRET_QUERY}&password={PASSWORD}",
        headers={"Cookie": f"__Host-easyaudit_session={SESSION_TOKEN}"},
    )
    client.get("/test/boom")

    output = log_output.getvalue()
    assert len(lines(log_output)) >= 3
    for secret in (PASSWORD, SESSION_TOKEN, SECRET_QUERY, "bearer-secret-1187", "__Host-"):
        assert secret not in output


def test_unhandled_exception_logs_type_and_frames_but_not_message(
    log_output: io.StringIO,
) -> None:
    client = TestClient(build_app(AuthStub()))

    response = client.get("/test/boom")

    request_id = response.headers["x-request-id"]
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error", "request_id": request_id}
    assert SECRET_EXCEPTION_TEXT not in response.text
    error = next(line for line in lines(log_output) if line["message"] == "unhandled_exception")
    assert error["level"] == "ERROR"
    assert error["request_id"] == request_id
    assert error["exception_type"].endswith("UnsafeError")
    assert any(frame.endswith(":boom") for frame in error["stack"])
    assert all(frame.count(":") >= 2 for frame in error["stack"])
    assert "sensitive-parameter-8842" not in log_output.getvalue()
    assert "exception_message" not in error
    [entry] = access_lines(log_output)
    assert entry["status_code"] == 500
    assert entry["request_id"] == request_id


def test_only_explicitly_allowed_exception_types_log_their_message(
    log_output: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(observability, "_SAFE_MESSAGE_EXCEPTIONS", {SafeError})
    client = TestClient(build_app(AuthStub()))

    client.get("/test/safe-boom")
    client.get("/test/boom")

    errors = [line for line in lines(log_output) if line["message"] == "unhandled_exception"]
    assert errors[0]["exception_message"] == "case is in a state that cannot be closed"
    assert "exception_message" not in errors[1]


def test_formatter_never_emits_exception_message_for_other_loggers() -> None:
    try:
        raise RuntimeError(SECRET_EXCEPTION_TEXT)
    except RuntimeError as exc:
        record = logging.LogRecord(
            "uvicorn.error",
            logging.ERROR,
            __file__,
            1,
            "Exception in ASGI application",
            None,
            (type(exc), exc, exc.__traceback__),
        )
    rendered = JsonFormatter().format(record)

    assert "sensitive-parameter-8842" not in rendered
    assert json.loads(rendered)["exception_type"] == "builtins.RuntimeError"


def test_log_config_uses_json_formatter_and_silences_uvicorn_access_log() -> None:
    config = build_log_config("WARNING")

    assert config["formatters"]["json"]["()"] == (
        "easyaudit_next.infrastructure.observability.JsonFormatter"
    )
    assert config["handlers"]["stdout"]["stream"] == "ext://sys.stdout"
    assert config["loggers"]["uvicorn.access"]["handlers"] == []
    assert config["loggers"]["uvicorn.access"]["propagate"] is False
    assert config["loggers"]["easyaudit"]["level"] == "WARNING"


def test_organization_and_actor_ids_are_uuids(log_output: io.StringIO) -> None:
    client = TestClient(build_app(AuthStub()))
    client.get("/test/cases/x", cookies={"__Host-easyaudit_session": SESSION_TOKEN})

    [entry] = access_lines(log_output)
    UUID(entry["organization_id"])
    UUID(entry["actor_user_id"])
    assert uuid4() != UUID(entry["actor_user_id"])
