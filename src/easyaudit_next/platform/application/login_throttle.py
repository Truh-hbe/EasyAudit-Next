"""Login attempt throttling: fixed windows, counted before the password is checked.

Counters are an operational record, not business truth (see docs/architecture.md). Keys are
stored only as sha256 digests.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from math import ceil

from easyaudit_next.platform.domain.repositories import LoginThrottleRepository

SCOPE_LOGIN_NAME = "login_name"
SCOPE_IP = "ip"
UNKNOWN_CLIENT = "unknown"


class LoginThrottledError(Exception):
    """Too many attempts in the current window. Carries nothing about the account."""

    def __init__(self, scopes: tuple[str, ...], retry_after_seconds: int) -> None:
        super().__init__("Too many login attempts")
        self.scopes = scopes
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class LoginThrottlePolicy:
    window: timedelta = timedelta(minutes=15)
    login_name_limit: int = 5
    ip_limit: int = 50


def key_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def window_start_for(at: datetime, window: timedelta) -> datetime:
    """Epoch-aligned, so the window boundary depends on time only, never on the key."""
    size = int(window.total_seconds())
    return datetime.fromtimestamp(int(at.timestamp()) // size * size, UTC)


class LoginThrottleService:
    def __init__(
        self,
        repository: LoginThrottleRepository,
        policy: LoginThrottlePolicy | None = None,
    ) -> None:
        self._repository = repository
        self._policy = policy or LoginThrottlePolicy()

    def register_attempt(self, login_name: str, client_ip: str | None, *, now: datetime) -> None:
        """Count this attempt on both dimensions atomically; raise if either is over its limit.

        Always locks the login_name row before the ip row (fixed order, no deadlocks). Both
        counters are incremented even when the first is already over the limit. The row locks
        are held until the request's transaction ends, so concurrent attempts on one key are
        serialized and the counts are exact.
        """
        window_start = window_start_for(now, self._policy.window)
        name_count = self._repository.increment(
            SCOPE_LOGIN_NAME, key_hash(login_name), window_start, now
        )
        ip_count = self._repository.increment(
            SCOPE_IP, key_hash(client_ip or UNKNOWN_CLIENT), window_start, now
        )
        scopes = tuple(
            scope
            for scope, count, limit in (
                (SCOPE_LOGIN_NAME, name_count, self._policy.login_name_limit),
                (SCOPE_IP, ip_count, self._policy.ip_limit),
            )
            if count > limit
        )
        if scopes:
            remaining = (window_start + self._policy.window - now).total_seconds()
            raise LoginThrottledError(scopes, max(1, ceil(remaining)))

    def record_success(self, login_name: str, *, now: datetime) -> None:
        """Reset the login_name counter of the current window. The ip counter is left alone:
        decrementing it would let one valid account offset guesses against others 1:1."""
        self._repository.reset(
            SCOPE_LOGIN_NAME,
            key_hash(login_name),
            window_start_for(now, self._policy.window),
            now,
        )

    def purge_expired(self, *, now: datetime) -> int:
        return self._repository.delete_before(window_start_for(now, self._policy.window))
