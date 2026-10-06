import pytest
from pydantic import ValidationError

from easyaudit_next.api.contracts import (
    CredentialResetRequest,
    LoginRequest,
    PasswordChangeRequest,
    UserCreateRequest,
)
from easyaudit_next.platform.application.password_policy import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
    validate_local_password,
)


def _reset(password: str) -> None:
    # The reset model only caps length; the service enforces the minimum before hashing.
    CredentialResetRequest(temporary_password=password)
    validate_local_password(password)


BOUNDARY_CASES = [(11, False), (12, True), (1000, True), (1001, False)]


def test_policy_bounds_are_12_and_1000() -> None:
    assert (MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH) == (12, 1000)


@pytest.mark.parametrize(("length", "valid"), BOUNDARY_CASES)
def test_service_policy_boundaries(length: int, valid: bool) -> None:
    password = "a" * length
    if valid:
        validate_local_password(password)
        return
    with pytest.raises(PasswordPolicyError) as raised:
        validate_local_password(password)
    assert password not in str(raised.value)


@pytest.mark.parametrize(("length", "valid"), BOUNDARY_CASES)
def test_set_and_reset_inputs_follow_policy(length: int, valid: bool) -> None:
    password = "a" * length
    builders = (
        lambda: _reset(password),
        lambda: UserCreateRequest(display_name="n", login_name="l", initial_password=password),
    )
    for build in builders:
        if valid:
            build()
        else:
            with pytest.raises((ValidationError, PasswordPolicyError)):
                build()


@pytest.mark.parametrize(("length", "valid"), [(1, True), (1000, True), (1001, False)])
def test_login_and_change_models_cap_at_policy_max(length: int, valid: bool) -> None:
    password = "a" * length
    builders = (
        lambda: LoginRequest(login_name="u", password=password),
        lambda: PasswordChangeRequest(current_password=password, new_password=password),
    )
    for build in builders:
        if valid:
            build()
        else:
            with pytest.raises((ValidationError, PasswordPolicyError)):
                build()
