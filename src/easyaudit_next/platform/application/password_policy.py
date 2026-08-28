class PasswordPolicyError(ValueError):
    """A local password does not meet the authoritative platform policy."""


def validate_local_password(password: str) -> None:
    """Apply the existing M1.2 local-password policy."""

    if len(password) < 12:
        raise PasswordPolicyError("Password must contain at least 12 characters")
