"""Login attempt throttling: fixed windows, counted before the password is checked.

Counters are an operational record, not business truth (see docs/architecture.md). Keys are
stored only as sha256 digests.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
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


ThrottleUnitOfWork = Callable[[], AbstractContextManager[LoginThrottleRepository]]


class LoginThrottleService:
    """Counting runs in its own short transaction, committed when the block exits.

    Counting must never share the request's transaction: its row locks would then be held
    through Argon2 and unrelated logins from the same IP would queue behind each other. It
    also happens before the request session has taken a connection, so a login never holds two.
    Only `record_success` uses the request's own transaction (`session_repository`).
    """

    def __init__(
        self,
        unit_of_work: ThrottleUnitOfWork,
        policy: LoginThrottlePolicy | None = None,
        *,
        session_repository: LoginThrottleRepository | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._policy = policy or LoginThrottlePolicy()
        self._session_repository = session_repository

    def register_attempt(self, login_name: str, client_ip: str | None, *, now: datetime) -> None:
        """Count this attempt on both dimensions atomically; raise if either is over its limit.

        One short transaction, committed before this returns or raises: the row locks last
        only for these two statements. Each upsert is atomic, so concurrent attempts on one
        key get distinct counts and at most `limit` of them proceed to password checking.
        Always locks the login_name row before the ip row (fixed order, no deadlocks). Both
        counters are incremented even when the first is already over the limit.
        """
        window_start = window_start_for(now, self._policy.window)
        with self._unit_of_work() as repository:
            name_count = repository.increment(
                SCOPE_LOGIN_NAME, key_hash(login_name), window_start, now
            )
            ip_count = repository.increment(
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
        """Reset the login_name counter of the current window, in the request's transaction.

        Called after Argon2 has finished, just before the request commits, so the row lock is
        held only for the last few statements and no second connection is needed. The ip
        counter is left alone: decrementing it would let one valid account offset guesses
        against others 1:1."""
        if self._session_repository is None:
            raise RuntimeError("record_success needs the request's session repository")
        self._session_repository.reset(
            SCOPE_LOGIN_NAME,
            key_hash(login_name),
            window_start_for(now, self._policy.window),
            now,
        )

    def purge_expired(self, *, now: datetime) -> int:
        with self._unit_of_work() as repository:
            return repository.delete_before(window_start_for(now, self._policy.window))

    def clear_login_name(self, login_name: str) -> int:
        """Operator escape hatch: drop every window's counter for one (normalized) login name."""
        with self._unit_of_work() as repository:
            return repository.delete_key(SCOPE_LOGIN_NAME, key_hash(login_name))
