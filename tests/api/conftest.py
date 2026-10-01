import io
import json
import logging
import logging.config
from collections.abc import Iterator
from typing import Any

import pytest

from easyaudit_next.infrastructure import readiness
from easyaudit_next.infrastructure.observability import build_log_config
from easyaudit_next.platform.settings import Settings

_LOGGER_NAMES = ("uvicorn", "uvicorn.error", "uvicorn.access", "easyaudit", "alembic")


class CapturedLogs:
    """Everything the production log config's handlers write (they target stdout)."""

    def __init__(self, buffer: io.StringIO) -> None:
        self._buffer = buffer

    def text(self) -> str:
        return self._buffer.getvalue()

    def lines(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.text().splitlines() if line.strip()]


@pytest.fixture
def log_output() -> Iterator[CapturedLogs]:
    """Apply `build_log_config` as the container does, redirecting its stdout handlers.

    pytest swaps `sys.stdout` between phases, so the `ext://sys.stdout` stream resolved at
    configuration time is stale by the time the test body runs; only the stream is replaced.
    """
    root = logging.getLogger()
    saved_root = (root.handlers[:], root.level)
    saved = {
        name: (
            logging.getLogger(name).handlers[:],
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
            logging.getLogger(name).disabled,
        )
        for name in _LOGGER_NAMES
    }
    logging.config.dictConfig(build_log_config("DEBUG"))
    buffer = io.StringIO()
    for logger in (root, *(logging.getLogger(name) for name in _LOGGER_NAMES)):
        for handler in logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                handler.setStream(buffer)
    # httpx is the *test client*: it logs the request URL (with query string) on its own.
    # That is client-side output, not something the server process would emit.
    httpx_logger = logging.getLogger("httpx")
    httpx_level = httpx_logger.level
    httpx_logger.setLevel(logging.WARNING)
    yield CapturedLogs(buffer)
    httpx_logger.setLevel(httpx_level)
    root.handlers[:], root.level = saved_root[0], saved_root[1]
    for name, (handlers, level, propagate, disabled) in saved.items():
        logger = logging.getLogger(name)
        logger.handlers[:] = handlers
        logger.setLevel(level)
        logger.propagate = propagate
        logger.disabled = disabled


@pytest.fixture(autouse=True)
def healthy_object_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """API tests have no object store; readiness tests of the bucket itself override this."""

    async def healthy(_: Settings) -> None:
        return None

    monkeypatch.setattr(readiness, "fetch_object_storage_failure", healthy)
