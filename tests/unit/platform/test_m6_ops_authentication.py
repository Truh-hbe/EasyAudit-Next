from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from easyaudit_next.platform.application.authentication import AuthenticationService


class TouchSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str, datetime]] = []

    def touch_if_active(self, session_id: object, token_hash: str, touched_at: datetime) -> None:
        self.calls.append((session_id, token_hash, touched_at))


def _service(spy: TouchSpy) -> AuthenticationService:
    return AuthenticationService(object(), spy, object(), object())  # type: ignore[arg-type]


def test_session_touch_issues_zero_writes_through_exact_ten_minute_window() -> None:
    t0 = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    session = SimpleNamespace(id="session", token_hash="token", last_seen_at=t0)
    for delta in (
        timedelta(minutes=1),
        timedelta(minutes=5),
        timedelta(minutes=9, seconds=59),
        timedelta(minutes=10),
    ):
        spy = TouchSpy()
        _service(spy).touch(session, now=t0 + delta)  # type: ignore[arg-type]
        assert spy.calls == []


def test_session_touch_delegates_one_stale_cas_after_threshold() -> None:
    t0 = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    session = SimpleNamespace(id="session", token_hash="token", last_seen_at=t0)
    spy = TouchSpy()
    touched_at = t0 + timedelta(minutes=10, microseconds=1)
    _service(spy).touch(session, now=touched_at)  # type: ignore[arg-type]
    assert spy.calls == [("session", "token", touched_at)]
