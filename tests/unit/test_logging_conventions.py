"""Log calls must carry constant event names and only structured, reviewed `extra`.

`JsonFormatter` renders `record.getMessage()`, so `logger.info("x %s", secret)` or an f-string
would put the value in the log; `extra={"fields": {...}}` is the place for variable data and is
additionally restricted at runtime by an allow-list of keys.

The check is by method name (debug/info/warning/error/exception/critical/log on any receiver),
not by receiver name, so aliases such as `audit_logger` or `self.logger` are covered too.
"""

import ast
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "easyaudit_next"
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}
ALLOWED_EXTRA_KEYS = {"fields", "exception_details"}


def _interpolates(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.JoinedStr):
            return True
        if isinstance(child, ast.BinOp) and isinstance(child.op, ast.Mod | ast.Add):
            return True
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name) and func.id in {"str", "repr", "format"}:
                return True
            if isinstance(func, ast.Attribute) and func.attr == "format":
                return True
    return False


def _extra_is_safe(value: ast.expr) -> bool:
    """A dict literal whose every key is an allowed string constant (no dynamic keys, no **)."""
    return isinstance(value, ast.Dict) and all(
        isinstance(key, ast.Constant) and key.value in ALLOWED_EXTRA_KEYS for key in value.keys
    )


def find_violations(source: str) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in LOG_METHODS
        ):
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        message_index = 1 if node.func.attr == "log" else 0
        message = (
            node.args[message_index] if len(node.args) > message_index else keywords.get("msg")
        )
        expands = None in keywords  # **payload
        if message is None and not expands:
            continue  # not a logging call shape
        bad = expands
        bad = bad or not (isinstance(message, ast.Constant) and isinstance(message.value, str))
        bad = bad or len(node.args) > message_index + 1
        bad = bad or _interpolates(node)
        if "extra" in keywords:
            bad = bad or not _extra_is_safe(keywords["extra"])
        if bad:
            lines.append(node.lineno)
    return lines


def test_source_tree_follows_the_logging_conventions() -> None:
    offenders = {
        f"{path.relative_to(SOURCE_ROOT)}:{line}"
        for path in SOURCE_ROOT.rglob("*.py")
        for line in find_violations(path.read_text(encoding="utf-8"))
    }
    assert offenders == set()


@pytest.mark.parametrize(
    "source",
    [
        'audit_logger.error(f"failed: {exc}")',
        'self.logger.exception(f"failed")',
        'logger.info("x %s", secret)',
        'logger.info("x %s" % secret)',
        'logger.info("x" + secret)',
        'logger.info("x {}".format(secret))',
        'APP_LOGGER.exception("event", extra={"fields": {"exception_message": str(exc)}})',
        'logger.info("event", extra=payload)',
        'logger.info("event", extra={"other": 1})',
        'logger.info("event", extra={**payload})',
        'logger.log(20, f"x {y}")',
        "logger.info(message)",
        'logger.error(msg=f"failed {exc}")',
        'logger.log(level=40, msg=f"failed {exc}")',
        'logger.info("event", extra={key: value})',
        'logger.info("event", **payload)',
        'logger.info("event", extra={"fields": {}, **more})',
    ],
)
def test_checker_flags_known_bypasses(source: str) -> None:
    assert find_violations(source) == [1]


@pytest.mark.parametrize(
    "source",
    [
        'APP_LOGGER.warning("event", extra={"fields": {"component": "db"}})',
        'self.log.error("event", exc_info=exc)',
        'logger.log(10, "event", extra={"fields": {"x": 1}, "exception_details": d})',
        'logger.log(level=10, msg="event")',
    ],
)
def test_checker_accepts_constant_messages_with_structured_extra(source: str) -> None:
    assert find_violations(source) == []
