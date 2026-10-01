import ast
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_architecture.py"
_spec = importlib.util.spec_from_file_location("check_architecture", SCRIPT)
assert _spec is not None and _spec.loader is not None
check_architecture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_architecture)


def _violations(
    call_arguments: str,
    function: str = "lock",
    class_name: str = "Repository",
    path: Path = Path("example.py"),
) -> list[str]:
    source = (
        f"class {class_name}:\n"
        f"    def {function}(self, select, read_mode):\n"
        f"        return select.with_for_update({call_arguments})\n"
    )
    return check_architecture.parent_lock_violations(path, ast.parse(source))


@pytest.mark.parametrize(
    "arguments",
    ["key_share=True", "read=True, key_share=True", "key_share=True, of=None"],
)
def test_no_key_update_and_key_share_are_allowed(arguments: str) -> None:
    assert _violations(arguments) == []


@pytest.mark.parametrize(
    "arguments",
    [
        "",
        "read=True",
        "key_share=False",
        "nowait=True",
        "read=read_mode",
        "key_share=read_mode",
        "read=True, key_share=read_mode",
        'key_share=True, **{"read": True}',
        "**{}",
    ],
)
def test_for_update_for_share_and_non_literal_modes_are_rejected(arguments: str) -> None:
    assert _violations(arguments) == ["example.py:3"]


def test_credential_lock_methods_are_allowlisted_by_file_class_and_method() -> None:
    path, class_name, function = sorted(check_architecture.FOR_UPDATE_ALLOWED_METHODS)[0]
    assert _violations("", function, class_name, path) == []
    # Same file and method name, different class.
    assert _violations("", function, "SqlAlchemyOtherRepository", path) == [f"{path}:3"]
    # Same class and method name, different file.
    assert _violations("", function, class_name) == ["example.py:3"]
