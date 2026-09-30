"""Log messages must be constant event names.

`JsonFormatter` renders `record.getMessage()`, so `logger.info("x %s", secret)` or an f-string
would put the value in the log. Variable data goes in `extra={"fields": {...}}` instead.
"""

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "easyaudit_next"
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
LOGGER_NAMES = {"APP_LOGGER", "ACCESS_LOGGER", "logger", "LOGGER", "log"}


def test_logger_calls_use_constant_messages_without_format_arguments() -> None:
    offenders: list[str] = []
    checked = 0
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in LOGGER_NAMES
            ):
                continue
            method = node.func.attr
            if method not in LOG_METHODS | {"log"}:
                continue
            checked += 1
            message_index = 1 if method == "log" else 0
            message = node.args[message_index] if len(node.args) > message_index else None
            constant = isinstance(message, ast.Constant) and isinstance(message.value, str)
            if not constant or len(node.args) > message_index + 1:
                offenders.append(f"{path.relative_to(SOURCE_ROOT)}:{node.lineno}")
    assert checked > 0
    assert offenders == []
