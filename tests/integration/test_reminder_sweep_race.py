"""Two-session races around the reminder sweep (real PostgreSQL).

- two sweeps with the same occurrence key at the same time never duplicate a delivery;
- the sweep never deadlocks against a Web member operation that locks
  `Organization -> Case -> User`, because every candidate is its own short transaction. The
  single-transaction mode (still used by in-process callers) is kept as the counter-example.
"""

import os
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event, Lock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from easyaudit_next import cli
from easyaudit_next.composition import build_automatic_reminder_sweep, build_review_planning_service
from easyaudit_next.notifications.persistence import NotificationRecord
from easyaudit_next.notifications.service import NotificationService
from easyaudit_next.platform.persistence.models import OrganizationRecord, UserRecord
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.domain.models import ScenarioKey, ScenarioVersion
from easyaudit_next.review_core.persistence.models import ReviewCaseRecord
from tests.integration.notification_test_support import NOW
from tests.integration.test_automatic_reminder import ReminderFixture, _seed_reminder_fixture

WAIT = 15


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _count(engine: Engine, organization_id) -> int:
    with Session(engine) as session:
        return (
            session.scalar(
                select(func.count())
                .select_from(NotificationRecord)
                .where(NotificationRecord.organization_id == organization_id)
            )
            or 0
        )


def _lock_waiters(engine: Engine) -> int:
    with engine.connect() as connection:
        return connection.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND wait_event_type = 'Lock'"
            )
        )


def _wait_for_lock_waiter(engine: Engine) -> None:
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        if _lock_waiters(engine):
            return
        time.sleep(0.05)
    raise AssertionError("no session ever waited for a lock")


def test_two_sweeps_with_same_key_overlapping_create_each_delivery_once(
    postgres_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    factory = sessionmaker(postgres_engine, autoflush=False, expire_on_commit=False)
    key = f"daily:{uuid4()}"
    inside, release = Event(), Event()
    first_call = Lock()
    original = NotificationService.deliver_automatic
    state = {"blocked": False}

    def hold_first_delivery(self, **kwargs):  # type: ignore[no-untyped-def]
        outcome = original(self, **kwargs)  # rows inserted, case row lock still held
        with first_call:
            hold = not state["blocked"]
            state["blocked"] = True
        if hold:
            inside.set()
            assert release.wait(WAIT)
        return outcome

    monkeypatch.setattr(NotificationService, "deliver_automatic", hold_first_delivery)

    def sweep() -> dict:
        return cli.run_reminder_sweep_job(
            factory, as_of=NOW, occurrence_key=key, organization_id=fixture.organization_id
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(sweep)
        assert inside.wait(WAIT)
        second = pool.submit(sweep)
        _wait_for_lock_waiter(postgres_engine)  # the second sweep queues behind the first
        release.set()
        results = [first.result(WAIT), second.result(WAIT)]

    assert [r["status"] for r in results] == ["succeeded", "succeeded"]
    assert sum(r["failed_count"] for r in results) == 0
    assert sum(r["created_count"] for r in results) == 4  # each (recipient, subject) once
    assert sum(r["deduped_count"] for r in results) == 4  # the loser's attempts were deduped
    assert _count(postgres_engine, fixture.organization_id) == 4


def _add_overdue_case(engine: Engine, fixture: ReminderFixture) -> UUID:
    with Session(engine, expire_on_commit=False) as session:
        lead = SqlAlchemyUserRepository(session).get(fixture.lead_id)
        assert lead is not None
        planning = build_review_planning_service(session)
        case = planning.create_case(
            lead,
            ScenarioKey("process_review"),
            ScenarioVersion(1),
            "Second overdue case",
            {"area_code": "ASSY", "review_type": "routine"},
            occurred_at=NOW,
        )
        for transition in ("schedule", "start"):
            case = planning.transition_case(lead, case.id, transition, occurred_at=NOW)
        session.execute(
            update(ReviewCaseRecord)
            .where(ReviewCaseRecord.id == case.id)
            .values(planned_end_at=NOW - timedelta(days=1))
        )
        session.commit()
        return case.id


def _web_member_operation(
    engine: Engine, fixture: ReminderFixture, case_id: UUID, holding: Event, proceed: Event
) -> None:
    """What `case_team_coordination` does: Organization -> Case -> User, all FOR UPDATE."""
    with Session(engine) as session, session.begin():
        session.execute(text("SET LOCAL lock_timeout = '12s'"))
        session.execute(
            select(OrganizationRecord.id)
            .where(OrganizationRecord.id == fixture.organization_id)
            .with_for_update()
        )
        session.execute(
            select(ReviewCaseRecord.id).where(ReviewCaseRecord.id == case_id).with_for_update()
        )
        holding.set()
        assert proceed.wait(WAIT)
        session.execute(
            select(UserRecord.id)
            .where(UserRecord.id.in_((fixture.lead_id, fixture.second_lead_id)))
            .order_by(UserRecord.id)
            .with_for_update()
        )


def _interleave(engine: Engine, run_sweep) -> tuple[list[BaseException], UUID]:  # type: ignore[no-untyped-def]
    """Web holds Org + the later-processed Case; the sweep finishes the earlier Case and then
    waits on the later one; only then the Web operation asks for the Users the sweep touched."""
    fixture = _seed_reminder_fixture(engine)
    second_case = _add_overdue_case(engine, fixture)
    later_case = max(fixture.review_case_id, second_case)  # candidates are processed by id
    holding, proceed = Event(), Event()
    errors: list[BaseException] = []

    def guarded(function, *args):  # type: ignore[no-untyped-def]
        try:
            function(*args)
        except BaseException as exc:  # noqa: BLE001 - collected and asserted by the caller
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        web = pool.submit(
            guarded, _web_member_operation, engine, fixture, later_case, holding, proceed
        )
        assert holding.wait(WAIT)
        sweep = pool.submit(guarded, run_sweep, fixture)
        _wait_for_lock_waiter(engine)  # sweep is queued behind the Web's Case lock
        proceed.set()
        web.result(WAIT * 2)
        sweep.result(WAIT * 2)
    return errors, fixture.organization_id


def test_sweep_does_not_deadlock_with_web_org_case_user_lock_order(
    postgres_engine: Engine,
) -> None:
    factory = sessionmaker(postgres_engine, autoflush=False, expire_on_commit=False)
    outcomes: list[dict] = []

    def run(fixture: ReminderFixture) -> None:
        outcomes.append(
            cli.run_reminder_sweep_job(
                factory,
                as_of=NOW,
                occurrence_key=f"daily:{uuid4()}",
                organization_id=fixture.organization_id,
            )
        )

    errors, organization_id = _interleave(postgres_engine, run)

    assert errors == []
    assert [o["status"] for o in outcomes] == ["succeeded"], outcomes
    assert outcomes[0]["failed_count"] == 0
    assert outcomes[0]["created_count"] == _count(postgres_engine, organization_id) > 0


def test_single_transaction_mode_deadlocks_in_the_same_interleaving(
    postgres_engine: Engine,
) -> None:
    """The old shape (one transaction for the whole sweep) forms a cycle with the same Web
    operation: this is why the CLI uses per-candidate transactions."""

    def run(fixture: ReminderFixture) -> None:
        with Session(postgres_engine) as session:
            session.execute(text("SET LOCAL lock_timeout = '12s'"))
            build_automatic_reminder_sweep(session).run_once(
                occurrence_key=f"daily:{uuid4()}",
                as_of=NOW,
                organization_id=fixture.organization_id,
            )
            session.commit()

    errors, _ = _interleave(postgres_engine, run)

    assert len(errors) == 1
    error = errors[0]
    assert isinstance(error, DBAPIError)
    assert getattr(error.orig, "sqlstate", None) == "40P01"  # deadlock_detected
