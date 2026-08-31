"""Pure submitted-login normalization shared by authentication and operational admission."""


def normalize_login_name(login_name: str) -> str:
    """Return the canonical login identity without performing I/O."""
    return login_name.strip().lower()
