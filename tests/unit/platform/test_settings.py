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


@pytest.mark.parametrize(
    "endpoint",
    [
        "",
        "http://object-storage:3900",
        "https://s3.example.com",
        "http://[::1]:3900/",
        "http://10.0.0.5",
    ],
)
def test_object_storage_endpoint_accepts_an_origin(endpoint: str) -> None:
    assert Settings(object_storage_endpoint=endpoint).object_storage_endpoint == endpoint


@pytest.mark.parametrize(
    "endpoint",
    [
        "ftp://storage:3900",
        "object-storage:3900",
        "http://",
        "http://storage:3900/prefix",
        "http://storage:3900/prefix/",
        "http://storage:3900?x=1",
        "http://storage:3900/#frag",
        "http://user:pw@storage:3900",
        "http://storage:notaport",
    ],
)
def test_object_storage_endpoint_rejects_anything_but_an_origin(endpoint: str) -> None:
    with pytest.raises(ValidationError):
        Settings(object_storage_endpoint=endpoint)
