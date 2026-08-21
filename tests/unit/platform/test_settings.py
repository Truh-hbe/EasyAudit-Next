import pytest
from pydantic import ValidationError

from easyaudit_next.platform.settings import Settings


@pytest.mark.parametrize("ttl", [0, 299, 2_592_001])
def test_session_ttl_rejects_unsafe_values(ttl: int) -> None:
    with pytest.raises(ValidationError):
        Settings(session_ttl_seconds=ttl)


def test_session_cookie_name_is_fixed_to_host_cookie() -> None:
    with pytest.raises(ValidationError):
        Settings(session_cookie_name="session")  # type: ignore[arg-type]
