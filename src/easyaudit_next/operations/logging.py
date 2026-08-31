from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_organization_id: ContextVar[str | None] = ContextVar("organization_id", default=None)
_actor_id: ContextVar[str | None] = ContextVar("actor_id", default=None)


class SafeJsonFormatter(logging.Formatter):
    """Formatter that never serializes arbitrary record messages or exceptions."""

    def format(self, record: logging.LogRecord) -> str:
        explicit = getattr(record, "easyaudit_fields", None)
        if isinstance(explicit, dict):
            payload: dict[str, Any] = dict(explicit)
        else:
            payload = {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": record.levelname,
                "event": "runtime_log",
                "request_id": _request_id.get(),
                "error_class": (
                    record.exc_info[0].__name__
                    if record.exc_info is not None and record.exc_info[0] is not None
                    else None
                ),
            }
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def configure_production_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(SafeJsonFormatter())

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)

    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    access.disabled = True

    for name in ("uvicorn.error", "fastapi"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True


def begin_request_context(request_id: str) -> tuple[Token[str | None], Token[str | None], Token[str | None]]:
    return (
        _request_id.set(request_id),
        _organization_id.set(None),
        _actor_id.set(None),
    )


def bind_authenticated_identity(organization_id: str, actor_id: str) -> None:
    _organization_id.set(organization_id)
    _actor_id.set(actor_id)


def current_identity_context() -> tuple[str | None, str | None]:
    return _organization_id.get(), _actor_id.get()


def reset_request_context(
    tokens: tuple[Token[str | None], Token[str | None], Token[str | None]]
) -> None:
    request_token, organization_token, actor_token = tokens
    _actor_id.reset(actor_token)
    _organization_id.reset(organization_token)
    _request_id.reset(request_token)


def log_request_completion(
    *,
    request_id: str,
    method: str,
    route: str,
    status_code: int,
    latency_ms: float,
    error_class: str | None,
) -> None:
    organization_id, actor_id = current_identity_context()
    logging.getLogger("easyaudit.request").info(
        "request_completed",
        extra={
            "easyaudit_fields": {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": "INFO" if status_code < 500 else "ERROR",
                "event": "http_request_completed",
                "request_id": request_id,
                "method": method,
                "route": route,
                "status_code": status_code,
                "latency_ms": max(latency_ms, 0.0),
                "organization_id": organization_id,
                "actor_id": actor_id,
                "error_class": error_class,
            }
        },
    )
