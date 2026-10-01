"""Logging for the operator commands: the same JSON formatter as the API, on stderr so that
stdout stays the command's single JSON result line."""

import logging
import sys

from easyaudit_next.infrastructure.observability import APP_LOGGER, JsonFormatter

_MARKER = "easyaudit_cli_handler"


def configure_cli_logging(level: str) -> None:
    APP_LOGGER.setLevel(level)
    if any(getattr(handler, _MARKER, False) for handler in APP_LOGGER.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    setattr(handler, _MARKER, True)
    APP_LOGGER.addHandler(handler)


def log_object_deleted_while_registered(storage_key: str, evidence_id: str) -> None:
    APP_LOGGER.error(
        "evidence_object_deleted_while_registered",
        extra={"fields": {"storage_key": storage_key, "evidence_id": evidence_id}},
    )
