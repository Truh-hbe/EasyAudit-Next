"""Readiness checks. Results carry no detail; callers log failures with their request id.

The database probe is fully async (psycopg ``AsyncConnection``, outside the application pool)
under one client-side deadline covering connect, query and close, so a stuck server or a
network black hole can never occupy the AnyIO thread pool shared with business endpoints.

Concurrency: single-flight. If a probe is already running, new callers await that same result
instead of opening another connection. Rationale: overlapping probes (orchestrator plus a
human) get a consistent answer, at most one probe connection exists at any time, and nobody
receives a false 503 merely because probes overlapped.

Object storage is probed for reachability only: a plain asyncio TCP (TLS for https) connection
and one unsigned `HEAD /{bucket}`; any well-formed HTTP status line counts as reachable, whether
200, 403 or 404. It runs concurrently with the database probe under the same deadline, with no
worker thread (a thread cannot be cancelled and botocore's timeouts are per-socket-operation,
not a total deadline: a server dripping bytes could keep one alive and delay process exit).
Credentials and the bucket itself are deliberately not validated here; a wrong key or bucket
shows up as an error on the first upload. Nothing is kept in module state.
"""

import asyncio
import ipaddress
import re
import socket
import threading
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import quote, urlsplit

import psycopg
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import AsyncConnection
from sqlalchemy.engine import make_url

from easyaudit_next.infrastructure.database import libpq_connect_kwargs
from easyaudit_next.infrastructure.observability import (
    APP_LOGGER,
    ExceptionDetails,
    describe_exception,
)
from easyaudit_next.platform.settings import DEFAULT_DATABASE_URL, Settings

CheckStatus = Literal["ok", "fail"]


@dataclass(frozen=True, slots=True)
class Failure:
    """A loggable failure. It never holds the exception object: a retained traceback would keep
    frames (and, after a timeout, a half-open database socket) alive."""

    component: str
    reason: str
    fields: dict[str, Any] = field(default_factory=dict)
    exception: ExceptionDetails | None = None

    @classmethod
    def of(
        cls, component: str, reason: str, exc: BaseException | None = None, **fields: Any
    ) -> "Failure":
        return cls(component, reason, fields, describe_exception(exc) if exc else None)


@dataclass(frozen=True, slots=True)
class DatabaseState:
    reachable: bool
    revisions: tuple[str, ...] | None  # None: could not be read
    failures: tuple[Failure, ...] = ()


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    checks: dict[str, CheckStatus]
    failures: tuple[Failure, ...]


def _compute_head() -> str:
    """Blocking file I/O; only ever called through `asyncio.to_thread`."""
    head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    if head is None:
        raise RuntimeError("alembic scripts have no head")
    return head


async def load_expected_head() -> str | None:
    """Head of the alembic scripts in this image (cwd holds alembic.ini), read once at startup.

    Failure returns None and is logged; there is no retry. Unreadable scripts mean the image
    itself is broken, so readiness stays failed until the process is restarted or rolled back.
    """
    try:
        return await asyncio.to_thread(_compute_head)
    except Exception as exc:
        APP_LOGGER.error(
            "expected_head_unavailable", extra={"exception_details": describe_exception(exc)}
        )
        return None


def log_failure(failure: Failure) -> None:
    APP_LOGGER.warning(
        "readiness_check_failed",
        extra={
            "fields": {"component": failure.component, "reason": failure.reason, **failure.fields},
            "exception_details": failure.exception,
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
        timeout = settings.readiness_timeout_seconds
        connection = await AsyncConnection.connect(
            **libpq_connect_kwargs(
                settings.database_url,
                connect_timeout=max(1, int(timeout)),
                statement_timeout_ms=int(timeout * 1000),
            ),
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
    any abnormal exit (deadline, or this coroutine being cancelled) the socket is closed at
    once, the probe is cancelled, and it is awaited for only a short grace period.
    """
    opened: list[AsyncConnection] = []
    probe = asyncio.ensure_future(_probe_database(settings, opened))
    probe.add_done_callback(_consume)
    completed = False
    try:
        done, _ = await asyncio.wait({probe}, timeout=settings.readiness_timeout_seconds)
        if probe in done:
            completed = True
            return probe.result()
        return DatabaseState(False, None, (Failure("database", "deadline_exceeded"),))
    finally:
        if not completed:
            for connection in opened:
                connection.pgconn.finish()
            probe.cancel()
            await asyncio.wait({probe}, timeout=CLEANUP_GRACE_SECONDS)


_STATUS_LINE = re.compile(rb"^HTTP/1\.[01] [1-5][0-9]{2}(?: |$)")
_CLOSE_GRACE_SECONDS = 0.25


async def _resolve(host: str, port: int) -> str:
    """Resolve in a daemon thread of our own. `getaddrinfo` cannot be interrupted: on the default
    executor a stuck resolver would delay the event loop's shutdown, whereas a daemon thread
    never blocks interpreter exit. A cancelled (timed-out) wait simply discards the result."""
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    loop = asyncio.get_running_loop()
    future: asyncio.Future[list[Any]] = loop.create_future()

    def deliver(addresses: list[Any] | None, error: BaseException | None) -> None:
        if future.done():
            return
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(addresses or [])

    def work() -> None:
        try:
            outcome: tuple[list[Any] | None, BaseException | None] = (
                socket.getaddrinfo(host, port, type=socket.SOCK_STREAM),
                None,
            )
        except BaseException as exc:
            outcome = (None, exc)
        try:
            loop.call_soon_threadsafe(deliver, *outcome)
        except RuntimeError:
            pass  # the loop is gone; nobody is waiting

    threading.Thread(target=work, daemon=True, name="readiness-resolve").start()
    infos = await future
    if not infos:
        raise OSError("name did not resolve")
    return str(infos[0][4][0])


def _head_request(settings: Settings) -> bytes:
    url = urlsplit(settings.object_storage_endpoint)
    host = f"[{url.hostname}]" if ":" in (url.hostname or "") else url.hostname
    host_header = host if url.port is None else f"{host}:{url.port}"
    bucket = quote(settings.object_storage_bucket, safe="")
    return f"HEAD /{bucket} HTTP/1.1\r\nHost: {host_header}\r\nConnection: close\r\n\r\n".encode()


async def _http_head_reachable(settings: Settings) -> None:
    """Raises on anything but a well-formed HTTP status line. Bounded by the caller's timeout;
    the socket is always closed, with a bounded wait. The endpoint format (origin only) is
    enforced by `Settings`."""
    url = urlsplit(settings.object_storage_endpoint)
    assert url.hostname is not None
    https = url.scheme == "https"
    port = url.port or (443 if https else 80)
    address = await _resolve(url.hostname, port)
    # Connect to the resolved address, but verify TLS (SNI and certificate) against the name.
    reader, writer = await asyncio.open_connection(
        address,
        port,
        ssl=True if https else None,
        server_hostname=url.hostname if https else None,
        limit=4096,
    )
    try:
        writer.write(_head_request(settings))
        await writer.drain()
        if not _STATUS_LINE.match(await reader.readline()):
            raise ValueError("not an HTTP response")
    finally:
        writer.close()
        try:
            async with asyncio.timeout(_CLOSE_GRACE_SECONDS):
                await writer.wait_closed()
        except Exception:
            pass


async def fetch_object_storage_failure(settings: Settings) -> Failure | None:
    """None means the endpoint answered HTTP within the readiness deadline."""
    if not (
        settings.object_storage_endpoint
        and settings.object_storage_bucket
        and settings.object_storage_access_key_id_file
        and settings.object_storage_secret_access_key_file
    ):
        return Failure("object_storage", "not_configured")
    try:
        async with asyncio.timeout(settings.readiness_timeout_seconds):
            await _http_head_reachable(settings)
    except TimeoutError:
        return Failure("object_storage", "deadline_exceeded")
    except Exception as exc:
        return Failure.of("object_storage", "unreachable", exc)
    return None


async def _evaluate(settings: Settings, expected_head: str | None) -> ReadinessResult:
    failures: list[Failure] = []
    config_failure = check_configuration(settings)
    if config_failure is not None:
        failures.append(config_failure)
    state, storage_failure = await asyncio.gather(
        fetch_database_state(settings), fetch_object_storage_failure(settings)
    )
    failures.extend(state.failures)
    if storage_failure is not None:
        failures.append(storage_failure)

    migrations_ok = False
    if state.revisions is not None:
        head = expected_head
        if head is None:
            failures.append(Failure("migrations", "expected_head_unavailable"))
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
        "object_storage": "fail" if storage_failure else "ok",
    }
    return ReadinessResult(checks, tuple(failures))


EVALUATION_GRACE_SECONDS = 1.0


async def _bounded(settings: Settings, expected_head: str | None) -> ReadinessResult:
    """Overall budget for the whole evaluation, independent of the per-step deadlines."""
    try:
        async with asyncio.timeout(settings.readiness_timeout_seconds + EVALUATION_GRACE_SECONDS):
            return await _evaluate(settings, expected_head)
    except TimeoutError:
        configuration: CheckStatus = "fail" if check_configuration(settings) else "ok"
        return ReadinessResult(
            {
                "configuration": configuration,
                "database": "fail",
                "migrations": "fail",
                "object_storage": "fail",
            },
            (Failure("readiness", "evaluation_deadline_exceeded"),),
        )


async def run_readiness(
    settings: Settings, expected_head: str | None, state: Any
) -> ReadinessResult:
    """Single-flight: concurrent callers share one in-progress evaluation.

    `state` is the application's `app.state`; the in-flight task lives there, not in module
    globals, so separate app instances never share results or event loops.
    """
    loop = asyncio.get_running_loop()
    task: asyncio.Task[ReadinessResult] | None = getattr(state, "readiness_inflight", None)
    if task is None or task.done() or task.get_loop() is not loop:
        task = loop.create_task(_bounded(settings, expected_head))
        state.readiness_inflight = task
    # shield: a caller that disconnects must not cancel the evaluation other callers wait on.
    return await asyncio.shield(task)
