from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from easyaudit_next import cli
from easyaudit_next.cli import build_parser
from easyaudit_next.platform.application.password_policy import PasswordPolicyError


def test_bootstrap_requires_explicit_identity_values_and_has_no_password_argument() -> None:
    args = build_parser().parse_args(
        [
            "bootstrap-admin",
            "--organization-name",
            "Example Organization",
            "--admin-name",
            "Administrator",
            "--login-name",
            "admin",
        ]
    )

    assert args.organization_name == "Example Organization"
    assert args.admin_name == "Administrator"
    assert args.login_name == "admin"
    assert not hasattr(args, "password")

    with pytest.raises(SystemExit):
        build_parser().parse_args(["bootstrap-admin", "--password", "default-password"])


def test_publish_scenario_requires_explicit_exact_identity() -> None:
    args = build_parser().parse_args(
        [
            "publish-scenario",
            "--organization-id",
            "11111111-1111-1111-1111-111111111111",
            "--key",
            "process_review",
            "--version",
            "1",
        ]
    )

    assert str(args.organization_id) == "11111111-1111-1111-1111-111111111111"
    assert args.key == "process_review"
    assert args.version == 1
    assert not hasattr(args, "policy")
    assert not hasattr(args, "schema")

    with pytest.raises(SystemExit):
        build_parser().parse_args(["publish-scenario", "--key", "process_review", "--version", "1"])


class _Scopes:
    """Stand-in for `session_scope` that records how many transactions are open."""

    def __init__(self) -> None:
        self.open = 0
        self.opened = 0

    @contextmanager
    def __call__(self, factory: object) -> Iterator[object]:
        self.open += 1
        self.opened += 1
        try:
            yield object()
        finally:
            self.open -= 1


class _Engine:
    def dispose(self) -> None:
        pass


def _patch_bootstrap(
    monkeypatch: pytest.MonkeyPatch, *, initialized: bool
) -> tuple[_Scopes, list[str]]:
    scopes = _Scopes()
    written: list[str] = []

    def ensure_available(session: object) -> None:
        if initialized:
            raise cli.BootstrapRefusedError("exists")

    monkeypatch.setattr(cli, "create_database_engine", lambda: _Engine())
    monkeypatch.setattr(cli, "create_session_factory", lambda engine: None)
    monkeypatch.setattr(cli, "session_scope", scopes)
    monkeypatch.setattr(cli, "_ensure_bootstrap_available", ensure_available)
    monkeypatch.setattr(
        cli, "bootstrap_admin_in_session", lambda session, *args: written.append(args[-1])
    )
    return scopes, written


def test_bootstrap_prompts_for_the_password_outside_any_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scopes, written = _patch_bootstrap(monkeypatch, initialized=False)
    open_during_prompt: list[int] = []

    def fake_getpass(prompt: str) -> str:
        open_during_prompt.append(scopes.open)
        return "a-long-enough-local-password-1"

    monkeypatch.setattr(cli.getpass, "getpass", fake_getpass)

    cli.bootstrap_admin("Org", "Admin", "admin")

    assert open_during_prompt == [0, 0]
    assert written == ["a-long-enough-local-password-1"]
    assert scopes.opened == 2


def test_bootstrap_does_not_prompt_when_already_initialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, written = _patch_bootstrap(monkeypatch, initialized=True)

    def fail_getpass(prompt: str) -> str:
        raise AssertionError("must not prompt")

    monkeypatch.setattr(cli.getpass, "getpass", fail_getpass)

    with pytest.raises(cli.BootstrapRefusedError):
        cli.bootstrap_admin("Org", "Admin", "admin")
    assert written == []


def test_bootstrap_password_mismatch_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    scopes, written = _patch_bootstrap(monkeypatch, initialized=False)
    answers = iter(["a-long-enough-local-password-1", "something-else-entirely-2"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(answers))

    with pytest.raises(PasswordPolicyError):
        cli.bootstrap_admin("Org", "Admin", "admin")
    assert written == []
    assert scopes.opened == 1
