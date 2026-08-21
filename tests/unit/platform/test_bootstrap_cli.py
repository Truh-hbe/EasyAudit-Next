import pytest

from easyaudit_next.cli import build_parser


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
