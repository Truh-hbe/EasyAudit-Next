from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest

from easyaudit_next.platform.application.login_throttle import (
    LoginThrottledError,
    LoginThrottlePolicy,
    LoginThrottleService,
    key_hash,
    window_start_for,
)

WINDOW = timedelta(minutes=15)
NOW = datetime(2031, 3, 1, 12, 1, 40, tzinfo=UTC)


class FakeRepository:
    def __init__(self) -> None:
        self.counts: dict[tuple[str, str, datetime], int] = {}
        self.calls: list[tuple[str, str]] = []

    def increment(self, scope: str, key_hash: str, window_start: datetime, now: datetime) -> int:
        self.calls.append(("increment", scope))
        key = (scope, key_hash, window_start)
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def reset(self, scope: str, key_hash: str, window_start: datetime, now: datetime) -> None:
        self.calls.append(("reset", scope))
        self.counts[(scope, key_hash, window_start)] = 0

    def delete_before(self, window_start: datetime) -> int:
        return 0

    def delete_key(self, scope: str, key_hash: str) -> int:
        return 0


def service(repo: FakeRepository, name_limit: int = 2, ip_limit: int = 3) -> LoginThrottleService:
    return LoginThrottleService(
        lambda: nullcontext(repo),
        LoginThrottlePolicy(WINDOW, name_limit, ip_limit),
        session_repository=repo,
    )


def test_windows_are_epoch_aligned() -> None:
    assert window_start_for(NOW, WINDOW) == datetime(2031, 3, 1, 12, 0, tzinfo=UTC)


def test_attempt_over_the_limit_raises_with_window_remainder_and_scope() -> None:
    throttle = service(FakeRepository())
    throttle.register_attempt("alice", "10.0.0.1", now=NOW)
    throttle.register_attempt("alice", "10.0.0.1", now=NOW)

    with pytest.raises(LoginThrottledError) as caught:
        throttle.register_attempt("alice", "10.0.0.1", now=NOW)

    assert caught.value.scopes == ("login_name",)
    assert caught.value.retry_after_seconds == 800


def test_both_dimensions_are_counted_login_name_first() -> None:
    repo = FakeRepository()
    with pytest.raises(LoginThrottledError):
        for _ in range(5):
            service(repo, name_limit=1).register_attempt("alice", None, now=NOW)

    assert repo.calls[:2] == [("increment", "login_name"), ("increment", "ip")]
    assert key_hash("unknown") in {key[1] for key in repo.counts}  # missing client ip bucket


def test_success_resets_login_name_only() -> None:
    repo = FakeRepository()
    throttle = service(repo)
    throttle.register_attempt("alice", "10.0.0.1", now=NOW)

    throttle.record_success("alice", now=NOW)

    assert repo.calls[-1] == ("reset", "login_name")
    assert ("reset", "ip") not in repo.calls
