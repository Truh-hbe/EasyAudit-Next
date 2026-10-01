"""Pilot-2B: PostgreSQL-backed login throttling (count first, verify after)."""

import logging
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, ClassVar
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from easyaudit_next import cli
from easyaudit_next.api import dependencies
from easyaudit_next.api.dependencies import get_database_session
from easyaudit_next.infrastructure.database import create_database_engine
from easyaudit_next.main import create_app
from easyaudit_next.platform.application import authentication
from easyaudit_next.platform.application.authentication import (
    AuthenticationService,
    InvalidCredentialsError,
)
from easyaudit_next.platform.application.login_throttle import (
    LoginThrottledError,
    LoginThrottlePolicy,
    LoginThrottleService,
    window_start_for,
)
from easyaudit_next.platform.persistence.models import LoginThrottleRecord, UserRecord
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyAuthSessionRepository,
    SqlAlchemyLocalCredentialRepository,
    SqlAlchemyLoginThrottleRepository,
    SqlAlchemyLoginThrottleUnitOfWork,
    SqlAlchemyPlatformAuditRepository,
    SqlAlchemyUserRepository,
)
from easyaudit_next.platform.settings import Settings
from tests.integration.test_credential_readiness import (
    P0,
    _seed_local_user,
)
from tests.integration.test_credential_readiness import postgres_engine as postgres_engine

LIMIT = 3
WINDOW = timedelta(minutes=15)
WRONG = "definitely-not-the-password"
# 100 s into an aligned window: the window remainder is 800 s.
T0 = datetime(2031, 3, 1, 12, 0, 0, tzinfo=UTC) + timedelta(seconds=100)


class _Clock(datetime):
    current: ClassVar[datetime] = T0

    @classmethod
    def now(cls, tz: Any = None) -> "_Clock":  # type: ignore[override]
        return cls.current  # type: ignore[return-value]


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> type[_Clock]:
    _Clock.current = T0
    monkeypatch.setattr(authentication, "datetime", _Clock)
    return _Clock


@pytest.fixture(autouse=True)
def small_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        login_throttle_window_seconds=int(WINDOW.total_seconds()),
        login_throttle_login_name_limit=LIMIT,
        login_throttle_ip_limit=1000,
    )
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)


def _random_ip() -> str:
    """Rows persist in the shared database and the clock is frozen: never reuse an address."""
    return ".".join(str(uuid4().int % 250 + 1) for _ in range(4))


def _client(ip: str | None = None) -> TestClient:
    ip = ip or _random_ip()
    return TestClient(create_app(), base_url="https://testserver", client=(ip, 50000))


def _post(client: TestClient, login_name: str, password: str) -> Any:
    return client.post("/api/v1/auth/login", json={"login_name": login_name, "password": password})


def _shape(response: Any) -> tuple[int, Any, dict[str, str]]:
    headers = {k: v for k, v in response.headers.items() if k.lower() != "x-request-id"}
    return response.status_code, response.json(), headers


def _deactivate(engine: Engine, login_name: str, user_id: UUID) -> None:
    with Session(engine) as session, session.begin():
        session.execute(update(UserRecord).where(UserRecord.id == user_id).values(is_active=False))


def _count(engine: Engine, scope: str, value: str, at: datetime = T0) -> int | None:
    with Session(engine) as session:
        row = session.get(
            LoginThrottleRecord,
            (scope, sha256(value.encode()).hexdigest(), window_start_for(at, WINDOW)),
        )
        return row.attempt_count if row is not None else None


def _account(kind: str, engine: Engine) -> str:
    if kind == "missing":
        return f"ghost-{uuid4().hex}"
    _, user_id, login_name = _seed_local_user(engine, must_change_password=False)
    if kind == "inactive":
        _deactivate(engine, login_name, user_id)
    return login_name


@pytest.mark.parametrize("kind", ["missing", "wrong_password", "inactive"])
def test_attempt_after_the_limit_is_429_even_with_the_right_password(
    postgres_engine: Engine, clock: type[_Clock], kind: str
) -> None:
    login_name = _account(kind, postgres_engine)
    client = _client()
    for _ in range(LIMIT):
        assert _post(client, login_name, WRONG).status_code == 401

    assert _post(client, login_name, P0).status_code == 429


def test_429_is_identical_whatever_the_account_state(
    postgres_engine: Engine, clock: type[_Clock]
) -> None:
    shapes_401: list[Any] = []
    shapes_429: list[Any] = []
    for kind in ("missing", "wrong_password", "inactive"):
        login_name = _account(kind, postgres_engine)
        client = _client()
        for _ in range(LIMIT):
            shapes_401.append(_shape(_post(client, login_name, WRONG)))
        shapes_429.append(_shape(_post(client, login_name, WRONG)))

    assert len({repr(shape) for shape in shapes_401}) == 1
    assert len({repr(shape) for shape in shapes_429}) == 1
    status, body, headers = shapes_429[0]
    assert status == 429
    assert body == {"detail": "Too many login attempts"}
    assert headers["retry-after"] == "800"  # window remainder: depends on time only


def test_ip_dimension_throttles_across_login_names_with_the_same_response(
    postgres_engine: Engine, clock: type[_Clock], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(login_throttle_login_name_limit=100, login_throttle_ip_limit=2)
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)
    client = _client(ip=_random_ip())
    by_ip = []
    for _ in range(2):
        assert _post(client, f"a-{uuid4().hex}", WRONG).status_code == 401
    by_ip.append(_shape(_post(client, f"b-{uuid4().hex}", WRONG)))

    monkeypatch.setattr(dependencies, "get_settings", lambda: Settings(
        login_throttle_login_name_limit=1, login_throttle_ip_limit=1000
    ))
    name = f"c-{uuid4().hex}"
    other = _client()
    _post(other, name, WRONG)
    by_name = _shape(_post(other, name, WRONG))

    assert by_ip[0] == by_name
    assert by_ip[0][0] == 429


def test_window_expiry_restores_login(postgres_engine: Engine, clock: type[_Clock]) -> None:
    login_name = _account("wrong_password", postgres_engine)
    client = _client()
    for _ in range(LIMIT):
        _post(client, login_name, WRONG)
    assert _post(client, login_name, P0).status_code == 429

    clock.current = T0 + timedelta(seconds=801)  # first instant of the next window

    assert _post(client, login_name, P0).status_code == 200


def test_success_resets_the_login_name_counter_only(
    postgres_engine: Engine, clock: type[_Clock]
) -> None:
    login_name = _account("wrong_password", postgres_engine)
    ip = _random_ip()
    client = _client(ip=ip)
    _post(client, login_name, WRONG)
    _post(client, login_name, WRONG)
    assert _post(client, login_name, P0).status_code == 200
    assert _count(postgres_engine, "login_name", login_name) == 0
    assert _count(postgres_engine, "ip", ip) == 3  # not decremented by the success

    for _ in range(LIMIT):
        assert _post(client, login_name, WRONG).status_code == 401
    assert _post(client, login_name, WRONG).status_code == 429


def test_throttled_attempts_are_committed_and_counted(
    postgres_engine: Engine, clock: type[_Clock]
) -> None:
    login_name = _account("missing", postgres_engine)
    client = _client()
    for _ in range(LIMIT + 2):
        _post(client, login_name, WRONG)

    assert _count(postgres_engine, "login_name", login_name) == LIMIT + 2


def test_database_holds_only_hashes_of_login_name_and_ip(
    postgres_engine: Engine, clock: type[_Clock]
) -> None:
    login_name = f"Plain-Name-{uuid4().hex}"
    ip = _random_ip()
    _post(_client(ip=ip), login_name, WRONG)

    normalized = login_name.strip().lower()
    with Session(postgres_engine) as session:
        rows = session.scalars(
            select(LoginThrottleRecord).where(
                LoginThrottleRecord.key_hash.in_(
                    [sha256(normalized.encode()).hexdigest(), sha256(ip.encode()).hexdigest()]
                )
            )
        ).all()
        assert {row.scope for row in rows} == {"login_name", "ip"}
        for row in session.scalars(select(LoginThrottleRecord)):
            dump = f"{row.scope}{row.key_hash}"
            assert normalized not in dump.lower()
            assert ip not in dump


def test_throttle_hit_logs_scope_only(
    postgres_engine: Engine, clock: type[_Clock], caplog: pytest.LogCaptureFixture
) -> None:
    login_name = _account("missing", postgres_engine)
    ip = _random_ip()
    client = _client(ip=ip)
    with caplog.at_level(logging.WARNING, logger="easyaudit.app"):
        for _ in range(LIMIT + 1):
            _post(client, login_name, WRONG)

    hits = [r for r in caplog.records if r.getMessage() == "login_throttled"]
    assert len(hits) == 1
    assert hits[0].fields == {"throttle_scope": "login_name"}  # type: ignore[attr-defined]
    assert login_name not in caplog.text
    assert ip not in caplog.text
    assert sha256(login_name.encode()).hexdigest() not in caplog.text


class _CountingHash:
    """Stands in for the Argon2 hasher; counts how many password checks actually happen."""

    def __init__(self) -> None:
        self.verifications = 0
        self._lock = threading.Lock()
        self._real = PasswordHash.recommended()

    def verify(self, password: str, hashed: str) -> bool:
        with self._lock:
            self.verifications += 1
        return self._real.verify(password, hashed)

    def hash(self, password: str) -> str:
        return self._real.hash(password)


def test_concurrent_attempts_on_one_key_never_exceed_the_limit(postgres_engine: Engine) -> None:
    login_name = _account("wrong_password", postgres_engine)
    ip = _random_ip()
    hasher = _CountingHash()
    attempts = LIMIT + 9
    now = datetime.now(UTC)
    barrier = threading.Barrier(attempts)
    policy = LoginThrottlePolicy(window=WINDOW, login_name_limit=LIMIT, ip_limit=1000)

    def attempt(_: int) -> str:
        with Session(postgres_engine) as session:
            service = AuthenticationService(
                SqlAlchemyLocalCredentialRepository(session),
                SqlAlchemyAuthSessionRepository(session),
                SqlAlchemyUserRepository(session),
                SqlAlchemyPlatformAuditRepository(session),
                login_throttle=LoginThrottleService(
                    SqlAlchemyLoginThrottleUnitOfWork(postgres_engine), policy
                ),
                password_hash=hasher,  # type: ignore[arg-type]
            )
            barrier.wait(timeout=10)
            try:
                service.login(login_name, WRONG, client_ip=ip, now=now)
                outcome = "ok"
            except LoginThrottledError:
                outcome = "throttled"
            except InvalidCredentialsError:
                outcome = "invalid"
            session.commit()
            return outcome

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        outcomes = list(pool.map(attempt, range(attempts)))

    assert outcomes.count("invalid") == LIMIT
    assert outcomes.count("throttled") == attempts - LIMIT
    assert hasher.verifications == LIMIT  # Argon2 ran only for attempts inside the limit
    assert _count(postgres_engine, "login_name", login_name.lower(), now) == attempts


def test_purge_removes_expired_windows_and_keeps_the_current_one(
    postgres_engine: Engine,
) -> None:
    now = datetime.now(UTC)
    current = window_start_for(now, WINDOW)
    marker = uuid4().hex
    keys = {name: sha256(f"{marker}-{name}".encode()).hexdigest() for name in ("old", "new")}
    with Session(postgres_engine) as session, session.begin():
        for name, start in (("old", current - WINDOW), ("new", current)):
            session.add(
                LoginThrottleRecord(
                    scope="login_name",
                    key_hash=keys[name],
                    window_start=start,
                    attempt_count=1,
                    updated_at=now,
                )
            )

    with Session(postgres_engine) as session, session.begin():
        removed = LoginThrottleService(
            lambda: nullcontext(SqlAlchemyLoginThrottleRepository(session)),
            LoginThrottlePolicy(window=WINDOW),
        ).purge_expired(now=now)
    assert removed >= 1

    with Session(postgres_engine) as session:
        remaining = set(
            session.scalars(
                select(LoginThrottleRecord.key_hash).where(
                    LoginThrottleRecord.key_hash.in_(list(keys.values()))
                )
            )
        )
    assert remaining == {keys["new"]}


class _MarkerSlowHash(_CountingHash):
    """Sleeps inside verify only for the marker password, so one request can be held in Argon2."""

    MARKER = "slow-password"

    def __init__(self, entered: threading.Event, seconds: float) -> None:
        super().__init__()
        self._entered = entered
        self._seconds = seconds

    def verify(self, password: str, hashed: str) -> bool:
        if password == self.MARKER:
            self._entered.set()
            time.sleep(self._seconds)
        return super().verify(password, hashed)


def test_a_slow_password_check_does_not_block_other_logins_from_the_same_ip(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through the HTTP route and the production dependency wiring (only the hasher is faked)."""
    first = _account("wrong_password", postgres_engine)
    second = _account("wrong_password", postgres_engine)
    ip = _random_ip()
    entered = threading.Event()
    slow_seconds = 2.0
    monkeypatch.setattr(
        authentication, "_DEFAULT_PASSWORD_HASH", _MarkerSlowHash(entered, slow_seconds)
    )
    outcome: dict[str, int] = {}

    def slow_login() -> None:
        outcome["slow"] = _post(_client(ip=ip), first, _MarkerSlowHash.MARKER).status_code

    worker = threading.Thread(target=slow_login)
    worker.start()
    try:
        assert entered.wait(timeout=10)  # the first login is now inside its (slow) Argon2
        started = time.monotonic()
        status = _post(_client(ip=ip), second, WRONG).status_code
        elapsed = time.monotonic() - started
    finally:
        worker.join(timeout=15)

    assert status == 401
    assert outcome["slow"] == 401
    # Counting inside the request transaction would queue this behind the first login's open
    # ip row lock for the rest of its Argon2.
    assert elapsed < slow_seconds / 2


def test_login_never_holds_two_connections_so_a_nearly_full_pool_cannot_stall_it(
    postgres_engine: Engine,
) -> None:
    """Smallest legal pool (2 connections) with one already taken elsewhere: a successful
    login (count, verify, reset, session insert) must still finish within pool_timeout."""
    small = create_database_engine(
        Settings(db_pool_size=1, db_max_overflow=1, db_pool_timeout_seconds=1.5)
    )
    login_name = _account("wrong_password", postgres_engine)
    app = create_app()

    def database_session() -> Iterator[Session]:
        with Session(small) as session:
            yield session
            session.commit()

    app.dependency_overrides[get_database_session] = database_session
    hogged = small.connect()
    try:
        client = TestClient(app, base_url="https://testserver", client=(_random_ip(), 50000))
        started = time.monotonic()
        response = _post(client, login_name, P0)
        elapsed = time.monotonic() - started
    finally:
        hogged.close()
        small.dispose()

    assert response.status_code == 200
    assert elapsed < 1.5


def test_fixed_window_boundary_admits_up_to_2n_attempts_across_two_windows(
    postgres_engine: Engine, clock: type[_Clock]
) -> None:
    login_name = _account("missing", postgres_engine)
    client = _client()
    window_end = window_start_for(T0, WINDOW) + WINDOW

    clock.current = window_end - timedelta(seconds=1)
    assert [_post(client, login_name, WRONG).status_code for _ in range(LIMIT)] == [401] * LIMIT
    assert _post(client, login_name, WRONG).status_code == 429

    clock.current = window_end  # the next window starts: the counter starts from zero again
    assert [_post(client, login_name, WRONG).status_code for _ in range(LIMIT)] == [401] * LIMIT
    assert _post(client, login_name, WRONG).status_code == 429


def test_clearing_a_login_name_unblocks_it(postgres_engine: Engine, clock: type[_Clock]) -> None:
    login_name = _account("wrong_password", postgres_engine)
    client = _client()
    for _ in range(LIMIT):
        _post(client, login_name, WRONG)
    assert _post(client, login_name, P0).status_code == 429

    with Session(postgres_engine) as session, session.begin():
        counts = cli.cleanup_auth_in_session(
            session, window=WINDOW, now=T0, clear_login_name=f"  {login_name.upper()} "
        )

    assert counts["login_name_cleared"] == 1
    assert _count(postgres_engine, "login_name", login_name) is None
    assert _post(client, login_name, P0).status_code == 200
