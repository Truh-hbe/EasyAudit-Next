from typing import get_args

from easyaudit_next.api.dependencies import AuthenticatedIdentity, DatabaseSession


def _dependency_scope(annotation: object) -> str | None:
    for metadata in get_args(annotation):
        scope = getattr(metadata, "scope", None)
        if scope is not None:
            return str(scope)
    return None


def test_database_transaction_finishes_before_response_is_sent() -> None:
    assert _dependency_scope(DatabaseSession) == "function"


def test_authenticated_identity_touch_finishes_in_same_pre_response_scope() -> None:
    assert _dependency_scope(AuthenticatedIdentity) == "function"
