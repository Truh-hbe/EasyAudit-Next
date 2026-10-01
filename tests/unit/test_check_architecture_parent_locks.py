import ast
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_architecture.py"
_spec = importlib.util.spec_from_file_location("check_architecture", SCRIPT)
assert _spec is not None and _spec.loader is not None
check_architecture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_architecture)


def _violations(call_arguments: str, function: str = "lock") -> list[str]:
    source = f"def {function}(select):\n    return select.with_for_update({call_arguments})\n"
    return check_architecture.parent_lock_violations(Path("example.py"), ast.parse(source))


@pytest.mark.parametrize(
    "arguments",
    ["key_share=True", "read=True, key_share=True", "key_share=True, of=None"],
)
def test_no_key_update_and_key_share_are_allowed(arguments: str) -> None:
    assert _violations(arguments) == []


@pytest.mark.parametrize("arguments", ["", "read=True", "key_share=False", "nowait=True"])
def test_for_update_and_for_share_are_rejected(arguments: str) -> None:
    assert _violations(arguments) == ["example.py:2"]


def test_credential_lock_functions_are_allowlisted() -> None:
    path, function = next(iter(check_architecture.FOR_UPDATE_ALLOWED_FUNCTIONS))
    source = f"def {function}(select):\n    return select.with_for_update()\n"
    assert check_architecture.parent_lock_violations(path, ast.parse(source)) == []
