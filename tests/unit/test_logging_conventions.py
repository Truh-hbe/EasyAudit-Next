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


def find_violations(source: str) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in LOG_METHODS
        ):
            continue
        message_index = 1 if node.func.attr == "log" else 0
        if len(node.args) <= message_index:
            continue  # not a logging call shape (e.g. a method without a message)
        message = node.args[message_index]
        bad = not (isinstance(message, ast.Constant) and isinstance(message.value, str))
        bad = bad or len(node.args) > message_index + 1
        bad = bad or _interpolates(node)
        for keyword in node.keywords:
            if keyword.arg == "extra":
                value = keyword.value
                keys = (
                    {k.value for k in value.keys if isinstance(k, ast.Constant)}
                    if isinstance(value, ast.Dict) and None not in value.keys
                    else None
                )
                bad = bad or keys is None or not keys <= ALLOWED_EXTRA_KEYS
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
    ],
)
def test_checker_accepts_constant_messages_with_structured_extra(source: str) -> None:
    assert find_violations(source) == []
