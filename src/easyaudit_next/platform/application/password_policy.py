MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1_000


class PasswordPolicyError(ValueError):
    """A local password does not meet the authoritative platform policy."""


def validate_local_password(password: str) -> None:
    """Apply the local-password length policy; callers must run it before hashing."""

    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must contain at least {MIN_PASSWORD_LENGTH} characters"
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"Password must contain at most {MAX_PASSWORD_LENGTH} characters")
