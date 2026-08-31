from __future__ import annotations

import json
import re
from time import monotonic
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from easyaudit_next.operations.logging import (
    begin_request_context,
    log_request_completion,
    reset_request_context,
)
from easyaudit_next.operations.metrics import metrics
from easyaudit_next.operations.rate_limit import LoginRateLimiter

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_LOGIN_PATH = "/api/v1/auth/login"
_MAX_LOGIN_BODY_BYTES = 16_384


def accepted_request_id(raw_value: str | None) -> str:
    if raw_value is not None and _REQUEST_ID.fullmatch(raw_value):
        return raw_value
    return uuid4().hex


def _header(scope: Scope, name: bytes) -> str | None:
    headers = scope.get("headers")
    if isinstance(headers, (list, tuple)):
        for item in headers:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                key, value = item
                if isinstance(key, bytes) and key.lower() == name and isinstance(value, bytes):
                    return str(value.decode("latin-1"))
    return None


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) and path else "__unmatched__"


class RequestObservabilityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = accepted_request_id(_header(scope, b"x-request-id"))
        context_tokens = begin_request_context(request_id)
        started = monotonic()
        status_code = 500
        response_started = False
        error_class: str | None = None

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message["status"])
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            try:
                await self.app(scope, receive, send_with_request_id)
            except Exception as exc:
                error_class = type(exc).__name__
                status_code = 500
                if not response_started:
                    body = b'{"detail":"Internal server error"}'
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 500,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode("ascii")),
                                (b"x-request-id", request_id.encode("ascii")),
                            ],
                        }
                    )
                    await send({"type": "http.response.body", "body": body})
        finally:
            elapsed = max(0.0, monotonic() - started)
            route = _route_template(scope)
            metrics.observe_http(
                method=str(scope.get("method", "")),
                route=route,
                status_code=status_code,
                duration_seconds=elapsed,
            )
            log_request_completion(
                request_id=request_id,
                method=str(scope.get("method", "")),
                route=route,
                status_code=status_code,
                latency_ms=elapsed * 1000.0,
                error_class=error_class,
            )
            reset_request_context(context_tokens)


class LoginAdmissionMiddleware:
    """API-edge admission control; throttled requests never reach authentication."""

    def __init__(self, app: ASGIApp, *, limiter: LoginRateLimiter) -> None:
        self.app = app
        self._limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != _LOGIN_PATH
        ):
            await self.app(scope, receive, send)
            return

        body, too_large = await _read_bounded_body(receive)
        if too_large:
            await _json_response(send, 413, {"detail": "Request body too large"})
            return

        login_name = _submitted_login(body)
        client = scope.get("client")
        source = str(client[0]) if isinstance(client, tuple) and client else "__unknown_peer__"
        decision = self._limiter.admit(login_name, source)
        if not decision.allowed:
            metrics.observe_authentication("throttled")
            await _json_response(
                send,
                429,
                {"detail": "Too many login attempts"},
                extra_headers=[
                    (b"retry-after", str(decision.retry_after_seconds).encode("ascii"))
                ],
            )
            return

        status_code = 500

        async def capture_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        await self.app(scope, _replay_body(body), capture_status)
        if 200 <= status_code < 300:
            metrics.observe_authentication("success")
        elif status_code == 401:
            metrics.observe_authentication("invalid")


async def _read_bounded_body(receive: Receive) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    while True:
        message = await receive()
        if message["type"] != "http.request":
            continue
        chunk = message.get("body", b"")
        total += len(chunk)
        if total > _MAX_LOGIN_BODY_BYTES:
            return b"", True
        chunks.append(chunk)
        if not message.get("more_body", False):
            return b"".join(chunks), False


def _replay_body(body: bytes) -> Receive:
    emitted = False

    async def receive() -> Message:
        nonlocal emitted
        if emitted:
            return {"type": "http.disconnect"}
        emitted = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def _submitted_login(body: bytes) -> str:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "__invalid_login_payload__"
    if isinstance(payload, dict):
        login_name = payload.get("login_name")
        if isinstance(login_name, str):
            return str(login_name)
    return "__invalid_login_payload__"


async def _json_response(
    send: Send,
    status_code: int,
    payload: dict[str, str],
    *,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status_code, "headers": headers})
    await send({"type": "http.response.body", "body": body})
