"""Readiness checks. Results carry no detail; callers log failures with their request id.

The database probe is fully async (psycopg ``AsyncConnection``, outside the application pool)
under one client-side deadline covering connect, query and close, so a stuck server or a
network black hole can never occupy the AnyIO thread pool shared with business endpoints.

Concurrency: single-flight. If a probe is already running, new callers await that same result
instead of opening another connection. Rationale: overlapping probes (orchestrator plus a
human) get a consistent answer, at most one probe connection exists at any time, and nobody
receives a false 503 merely because probes overlapped.

Object storage is deliberately not checked: the application does not use it yet. Pilot-4A adds
it here together with Evidence upload.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal

import psycopg
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import AsyncConnection
from sqlalchemy.engine import make_url

from easyaudit_next.infrastructure.observability import APP_LOGGER, describe_exception
from easyaudit_next.platform.settings import DEFAULT_DATABASE_URL, Settings

CheckStatus = Literal["ok", "fail"]


@dataclass(frozen=True, slots=True)
class Failure:
    """A loggable failure. It never holds the exception object: a retained traceback would keep
    frames (and, after a timeout, a half-open database socket) alive."""

    component: str
    reason: str
    fields: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def of(
        cls, component: str, reason: str, exc: BaseException | None = None, **fields: Any
    ) -> "Failure":
        if exc is not None:
            fields = {**fields, **describe_exception(exc)}
        return cls(component, reason, fields)


@dataclass(frozen=True, slots=True)
class DatabaseState:
    reachable: bool
    revisions: tuple[str, ...] | None  # None: could not be read
    failures: tuple[Failure, ...] = ()


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    checks: dict[str, CheckStatus]
    failures: tuple[Failure, ...]


@lru_cache
def get_expected_head() -> str:
    """Head of the alembic scripts shipped in this image (cwd holds alembic.ini, as for migrate)."""
    head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    if head is None:
        raise RuntimeError("alembic scripts have no head")
    return head


def log_failure(failure: Failure) -> None:
    APP_LOGGER.warning(
        "readiness_check_failed",
        extra={
            "fields": {"component": failure.component, "reason": failure.reason, **failure.fields}
        },
    )


def check_configuration(settings: Settings) -> Failure | None:
    if not settings.database_url:
        return Failure("configuration", "database_url_missing")
    try:
        make_url(settings.database_url)
    except Exception as exc:
        return Failure.of("configuration", "database_url_invalid", exc)
    if settings.app_env != "development" and settings.database_url == DEFAULT_DATABASE_URL:
        return Failure("configuration", "database_url_is_development_default")
    return None


# After the deadline we still give the abandoned probe this long to unwind before moving on.
CLEANUP_GRACE_SECONDS = 0.25


async def _probe_database(settings: Settings, opened: list[AsyncConnection]) -> DatabaseState:
    reachable = False
    try:
        url = make_url(settings.database_url)
        timeout = settings.readiness_timeout_seconds
        connection = await AsyncConnection.connect(
            host=url.host,
            port=url.port,
            user=url.username,
            password=url.password,
            dbname=url.database,
            connect_timeout=max(1, int(timeout)),
            options=f"-c statement_timeout={int(timeout * 1000)}",
            autocommit=True,
        )
        opened.append(connection)
        async with connection:
            await connection.execute("SELECT 1")
            reachable = True
            try:
                cursor = await connection.execute("SELECT version_num FROM alembic_version")
                revisions = tuple(sorted(row[0] for row in await cursor.fetchall()))
            except psycopg.errors.UndefinedTable:
                revisions = ()
        return DatabaseState(True, revisions)
    except Exception as exc:
        if reachable:
            return DatabaseState(True, None, (Failure.of("migrations", "unreadable", exc),))
        return DatabaseState(False, None, (Failure.of("database", "unreachable", exc),))


def _consume(task: "asyncio.Future[DatabaseState]") -> None:
    if not task.cancelled():
        task.exception()  # mark as retrieved; the probe reports its own failures


async def fetch_database_state(settings: Settings) -> DatabaseState:
    """One short-lived connection under one hard client-side deadline.

    The deadline is enforced from outside the probe: psycopg itself waits up to 5s for a
    server-side cancel when a query task is cancelled, which would overrun our budget. On
    deadline the socket is closed at once and the probe is cancelled without waiting on it
    beyond a short grace period.
    """
    opened: list[AsyncConnection] = []
    probe = asyncio.ensure_future(_probe_database(settings, opened))
    probe.add_done_callback(_consume)
    try:
        done, _ = await asyncio.wait({probe}, timeout=settings.readiness_timeout_seconds)
        if probe in done:
            return probe.result()
        for connection in opened:
            connection.pgconn.finish()
        probe.cancel()
        await asyncio.wait({probe}, timeout=CLEANUP_GRACE_SECONDS)
        return DatabaseState(False, None, (Failure("database", "deadline_exceeded"),))
    except asyncio.CancelledError:
        probe.cancel()
        raise


async def _evaluate(settings: Settings, expected_head: Callable[[], str]) -> ReadinessResult:
    failures: list[Failure] = []
    config_failure = check_configuration(settings)
    if config_failure is not None:
        failures.append(config_failure)
    state = await fetch_database_state(settings)
    failures.extend(state.failures)

    migrations_ok = False
    if state.revisions is not None:
        try:
            head = expected_head()
        except Exception as exc:
            failures.append(Failure.of("migrations", "expected_head_unavailable", exc))
        else:
            migrations_ok = state.revisions == (head,)
            if not migrations_ok:
                failures.append(
                    Failure.of(
                        "migrations",
                        "revision_mismatch",
                        current_revision=list(state.revisions),
                        expected_revision=head,
                    )
                )
    checks: dict[str, CheckStatus] = {
        "configuration": "fail" if config_failure else "ok",
        "database": "ok" if state.reachable else "fail",
        "migrations": "ok" if migrations_ok else "fail",
    }
    return ReadinessResult(checks, tuple(failures))


_inflight: asyncio.Task[ReadinessResult] | None = None


async def run_readiness(settings: Settings, expected_head: Callable[[], str]) -> ReadinessResult:
    """Single-flight: concurrent callers share one in-progress evaluation."""
    global _inflight
    loop = asyncio.get_running_loop()
    task = _inflight
    if task is None or task.done() or task.get_loop() is not loop:
        task = loop.create_task(_evaluate(settings, expected_head))
        _inflight = task
    # shield: a caller that disconnects must not cancel the evaluation other callers wait on.
    return await asyncio.shield(task)
