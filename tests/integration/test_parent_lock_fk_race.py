"""Parent-row locks must not deadlock against FK `FOR KEY SHARE` taken by child INSERTs.

A request that already inserted a row referencing a User / Case (KEY SHARE) and then inserts a
Notification (KEY SHARE on the Organization) used to deadlock with Case-team management /
deactivation, which holds the Organization `FOR UPDATE` and waits for that User / Case. Parent-row
locks are `FOR NO KEY UPDATE`, which does not conflict with KEY SHARE.

Each race pauses the writer right before its Notification INSERT, runs the manager until it either
finishes or blocks on a lock (`pg_stat_activity`), then releases the writer.
"""

import os
import re
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from easyaudit_next.composition import (
    build_automatic_reminder_evaluator,
    build_case_team_coordinator,
    build_manual_nudge_service,
    build_notification_orchestrator,
    build_rectification_service,
)
from easyaudit_next.platform.domain.ids import UserId
from easyaudit_next.platform.persistence.models import UserRecord
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyOrganizationRepository,
    SqlAlchemyUserRepository,
)
from easyaudit_next.review_core.domain.models import AssignmentRole, UserActor
from easyaudit_next.review_core.persistence.models import FindingRecord
from easyaudit_next.review_core.persistence.repositories import SqlAlchemyReviewCoreRepository
from easyaudit_next.review_core.persistence.verification_repositories import (
    SqlAlchemyVerificationClosureRepository,
)
from tests.integration.notification_test_support import NOW
from tests.integration.test_m5_3_case_team_management import _identity_client
from tests.integration.test_manual_nudge import NudgeFixture, _seed_nudge_fixture

pytestmark = pytest.mark.skipif(
    os.environ.get("EASYAUDIT_RUN_POSTGRES_TESTS") != "1",
    reason="PostgreSQL integration tests are opt-in outside CI",
)

NOTIFICATION_INSERT = re.compile(r"INSERT INTO notifications")
_writer = threading.local()


class _Backend:
    """PostgreSQL backend PID of the manager's connection.

    Recorded from the first statement run by any thread that is not the paused writer (the HTTP
    manager runs in the TestClient's own thread, so a thread-local would not see it).
    """

    pid: int | None = None


_manager_backend: _Backend | None = None


class _Pause:
    def __init__(self) -> None:
        self.reached = threading.Event()
        self.release = threading.Event()


@dataclass(frozen=True)
class _Ids:
    admin: UserId
    case: UUID
    other: UserId
    reviewer: UserId


@pytest.fixture
def engines() -> Iterator[tuple[Engine, Engine, str]]:
    name = f"parent-lock-{uuid4().hex[:8]}"
    url = os.environ["DATABASE_URL"]
    app_engine = create_engine(url, pool_size=10, connect_args={"application_name": name})

    @event.listens_for(app_engine, "before_cursor_execute")
    def pause_writer(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        pause: _Pause | None = getattr(_writer, "pause", None)
        backend = _manager_backend
        if pause is None and backend is not None and backend.pid is None:
            backend.pid = conn.connection.dbapi_connection.info.backend_pid
        if pause is not None and NOTIFICATION_INSERT.search(statement):
            if not pause.reached.is_set():
                pause.reached.set()
                assert pause.release.wait(30), "writer was never released"

    observer = create_engine(url)
    yield app_engine, observer, name
    app_engine.dispose()
    observer.dispose()


def _ids(engine: Engine, fixture: NudgeFixture) -> _Ids:
    def user(session: Session, **where: object) -> UserId:
        found = session.scalar(
            select(UserRecord.id).where(
                UserRecord.organization_id == fixture.organization_id,
                *(getattr(UserRecord, key) == value for key, value in where.items()),
            )
        )
        assert found is not None
        return UserId(found)

    with Session(engine) as session:
        case_id = session.scalar(
            select(FindingRecord.case_id).where(FindingRecord.id == fixture.finding_id)
        )
        assert case_id is not None
        return _Ids(
            admin=user(session, platform_role="system_admin"),
            case=case_id,
            other=user(session, display_name="Unrelated"),
            reviewer=user(session, display_name="Reviewer"),
        )


def _outcome(call: Callable[[], Any]) -> str:
    try:
        call()
    except DBAPIError as error:
        return f"{type(error.orig).__name__} sqlstate={getattr(error.orig, 'sqlstate', None)}"
    return "ok"


def _wait_until_done_or_blocked(
    observer: Engine, manager_backend: _Backend, manager: Future[str]
) -> None:
    """Fail unless the manager finishes or *its own backend* is waiting on a lock."""

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if manager.done():
            return
        if manager_backend.pid is not None:
            with observer.connect() as connection:
                blocked = connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE pid = :pid AND wait_event_type = 'Lock'"
                    ),
                    {"pid": manager_backend.pid},
                )
            if blocked:
                return
        time.sleep(0.05)
    pytest.fail("manager neither finished nor blocked on a lock within 15s")


def _race(
    engines: tuple[Engine, Engine, str],
    writer: Callable[[], Any],
    manager: Callable[[], Any],
) -> tuple[str, str]:
    _, observer, _ = engines
    pause = _Pause()
    manager_backend = _Backend()

    def run_writer() -> str:
        _writer.pause = pause
        return _outcome(writer)

    global _manager_backend
    with ThreadPoolExecutor(max_workers=2) as pool:
        writer_future = pool.submit(run_writer)
        assert pause.reached.wait(30), "writer never reached its Notification INSERT"
        _manager_backend = manager_backend
        try:
            manager_future = pool.submit(lambda: _outcome(manager))
            _wait_until_done_or_blocked(observer, manager_backend, manager_future)
        finally:
            pause.release.set()
            _manager_backend = None
        return writer_future.result(40), manager_future.result(40)


def _writer_nudge(engine: Engine, fixture: NudgeFixture) -> Callable[[], Any]:
    def run() -> Any:
        with Session(engine) as session, session.begin():
            lead = SqlAlchemyUserRepository(session).get(fixture.lead_id)
            assert lead is not None
            return build_manual_nudge_service(session).nudge_finding(
                lead, fixture.finding_id, occurred_at=NOW
            )

    return run


def _writer_assign(engine: Engine, fixture: NudgeFixture, target: UserId) -> Callable[[], Any]:
    def run() -> None:
        with Session(engine) as session, session.begin():
            owner = SqlAlchemyUserRepository(session).get(fixture.owner_id)
            assert owner is not None
            result = build_rectification_service(session).add_assignee_result(
                owner,
                fixture.action_item_id,
                UserActor(target),
                AssignmentRole.COLLABORATOR,
                occurred_at=NOW,
            )
            build_notification_orchestrator(session).action_assignee_added(result)

    return run


def _writer_submit(engine: Engine, fixture: NudgeFixture) -> Callable[[], Any]:
    def run() -> None:
        with Session(engine) as session, session.begin():
            owner = SqlAlchemyUserRepository(session).get(fixture.owner_id)
            assert owner is not None
            result = build_rectification_service(session).submit_rectification_result(
                owner,
                fixture.finding_id,
                "submit_for_verification",
                {"stage": "completion", "comment": "ready"},
                occurred_at=NOW,
            )
            build_notification_orchestrator(session).rectification_submitted(result)

    return run


def _manager_add_member(
    engine: Engine, fixture: NudgeFixture, case_id: UUID, user_id: UserId
) -> Callable[[], Any]:
    def run() -> Any:
        with Session(engine) as session, session.begin():
            lead = SqlAlchemyUserRepository(session).get(fixture.lead_id)
            assert lead is not None
            return build_case_team_coordinator(session).add_case_member_result(
                lead, case_id, user_id, "lead"  # type: ignore[arg-type]
            )

    return run


def _manager_deactivate(engine: Engine, admin_id: UserId, target: UserId) -> Callable[[], Any]:
    def run() -> Any:
        with Session(engine) as session, session.begin():
            admin = SqlAlchemyUserRepository(session).get(admin_id)
            assert admin is not None
            return build_case_team_coordinator(session).update_user(admin, target, is_active=False)

    return run


def _seed(engine: Engine) -> tuple[NudgeFixture, _Ids]:
    fixture = _seed_nudge_fixture(engine)
    return fixture, _ids(engine, fixture)


def test_nudge_does_not_deadlock_with_case_member_add(
    engines: tuple[Engine, Engine, str],
) -> None:
    """User edge: the nudge holds KEY SHARE on its actor; the manager locks that User."""

    engine = engines[0]
    fixture, ids = _seed(engine)
    results = _race(
        engines,
        _writer_nudge(engine, fixture),
        _manager_add_member(engine, fixture, ids.case, ids.reviewer),
    )
    assert results == ("ok", "ok")


def test_rectification_submit_does_not_deadlock_with_case_member_add(
    engines: tuple[Engine, Engine, str],
) -> None:
    """Case edge: the submission holds KEY SHARE on the Case; the manager locks that Case."""

    engine = engines[0]
    fixture, ids = _seed(engine)
    with Session(engine) as session, session.begin():
        assignee = SqlAlchemyUserRepository(session).get(fixture.assignee_id)
        lead = SqlAlchemyUserRepository(session).get(fixture.lead_id)
        assert assignee is not None and lead is not None
        rectification = build_rectification_service(session)
        rectification.transition_action_item(
            assignee, fixture.action_item_id, "start", occurred_at=NOW
        )
        rectification.transition_action_item(
            assignee, fixture.action_item_id, "complete", occurred_at=NOW
        )
        # A verifier must exist, otherwise no Notification is written.
        build_case_team_coordinator(session).add_case_member_result(
            lead, ids.case, ids.reviewer, "reviewer"  # type: ignore[arg-type]
        )
    results = _race(
        engines,
        _writer_submit(engine, fixture),
        _manager_add_member(engine, fixture, ids.case, ids.other),
    )
    assert results == ("ok", "ok")


def test_assignee_add_does_not_deadlock_with_deactivation_of_the_assignee(
    engines: tuple[Engine, Engine, str],
) -> None:
    engine = engines[0]
    fixture, ids = _seed(engine)
    results = _race(
        engines,
        _writer_assign(engine, fixture, ids.other),
        _manager_deactivate(engine, ids.admin, ids.other),
    )
    assert results == ("ok", "ok")


def test_http_member_add_returns_201_while_a_nudge_is_in_flight(
    engines: tuple[Engine, Engine, str],
) -> None:
    engine = engines[0]
    fixture, ids = _seed(engine)
    client = TestClient(
        _identity_client(engine, fixture.lead_id).app,
        base_url="https://testserver",
        raise_server_exceptions=False,
    )
    statuses: list[int] = []

    def add_member() -> None:
        response = client.post(
            f"/api/v1/review-cases/{ids.case}/members",
            json={"user_id": str(ids.reviewer), "role_key": "lead"},
        )
        statuses.append(response.status_code)

    results = _race(engines, _writer_nudge(engine, fixture), add_member)
    assert results == ("ok", "ok")
    assert statuses == [201]


def test_parent_row_locks_compile_to_for_no_key_update(
    engines: tuple[Engine, Engine, str],
) -> None:
    """All 8 parent-row locks are FOR NO KEY UPDATE (the lock mode, not just the call shape)."""

    engine, _, _ = engines
    captured: list[str] = []

    fixture, ids = _seed(engine)

    @event.listens_for(engine, "before_cursor_execute")
    def capture(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        captured.append(statement)

    organization_id, case_id = fixture.organization_id, ids.case
    with Session(engine) as session, session.begin():
        SqlAlchemyOrganizationRepository(session).lock_for_update(organization_id)
        SqlAlchemyUserRepository(session).lock_users_for_update(organization_id, (ids.admin,))
        SqlAlchemyReviewCoreRepository(session).lock_case_for_team_management(
            organization_id, case_id
        )
        verification = SqlAlchemyVerificationClosureRepository(session)
        verification.lock_case_for_closure(organization_id, case_id)
        verification.lock_finding_for_verification(organization_id, fixture.finding_id)
        verification.lock_finding_for_rectification(organization_id, fixture.finding_id)
        # Private on purpose: the guard SELECTs are the only way to reach these two locks
        # without scheduling a real overdue occurrence.
        evaluator = build_automatic_reminder_evaluator(session)
        evaluator._load_case(organization_id, case_id, guard=True)
        evaluator._load_action(organization_id, fixture.action_item_id, guard=True)
    locks = [statement for statement in captured if " FOR " in statement]
    assert len(locks) == 8
    for statement in locks:
        assert statement.rstrip().endswith("FOR NO KEY UPDATE"), statement
