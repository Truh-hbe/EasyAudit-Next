"""`run-reminder-sweep` / `scheduler-status` against real PostgreSQL."""

import json
import os
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from easyaudit_next import cli
from easyaudit_next.collaboration.reminder_sweep import AutomaticReminderSweep
from easyaudit_next.collaboration.scheduler_runs import (
    JOB_AUTOMATIC_REMINDER_SWEEP,
    SchedulerRunRecord,
)
from easyaudit_next.notifications.models import NotificationKind
from easyaudit_next.notifications.persistence import NotificationRecord
from easyaudit_next.notifications.service import NotificationService
from easyaudit_next.review_core.persistence.models import ReviewCaseRecord
from tests.integration.notification_test_support import NOW
from tests.integration.test_automatic_reminder import _seed_reminder_fixture

KEY = "daily:2026-10-02"
AUTOMATIC_KINDS = (
    NotificationKind.AUTOMATIC_CASE_REMINDER.value,
    NotificationKind.AUTOMATIC_ACTION_REMINDER.value,
)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def factory(postgres_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(postgres_engine, autoflush=False, expire_on_commit=False)


def _notifications(engine: Engine, organization_id, kind: str | None = None) -> int:
    with Session(engine) as session:
        return (
            session.scalar(
                select(func.count())
                .select_from(NotificationRecord)
                .where(
                    NotificationRecord.organization_id == organization_id,
                    NotificationRecord.kind.in_(AUTOMATIC_KINDS if kind is None else (kind,)),
                )
            )
            or 0
        )


def _run(factory: sessionmaker[Session], organization_id, key: str = KEY) -> dict:
    return cli.run_reminder_sweep_job(
        factory, as_of=NOW, occurrence_key=key, organization_id=organization_id
    )


def _rows(engine: Engine, key: str) -> list[SchedulerRunRecord]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(SchedulerRunRecord)
                .where(SchedulerRunRecord.occurrence_key == key)
                .order_by(SchedulerRunRecord.started_at)
            )
        )


def test_second_run_with_same_key_creates_nothing_and_counts_dedupes(
    postgres_engine: Engine, factory: sessionmaker[Session]
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    key = f"daily:{uuid4()}"
    first = _run(factory, fixture.organization_id, key)
    second = _run(factory, fixture.organization_id, key)

    assert first["status"] == second["status"] == "succeeded"
    assert first["scanned_count"] == second["scanned_count"] == 2
    assert first["created_count"] == 4
    assert second["created_count"] == 0
    assert second["deduped_count"] == first["created_count"]
    assert _notifications(postgres_engine, fixture.organization_id) == 4
    rows = _rows(postgres_engine, key)
    assert [row.status for row in rows] == ["succeeded", "succeeded"]
    assert all(row.finished_at is not None and row.failed_count == 0 for row in rows)
    assert (rows[1].created_count, rows[1].deduped_count) == (0, 4)


def test_rerun_really_executes_despite_succeeded_and_running_records(
    postgres_engine: Engine, factory: sessionmaker[Session]
) -> None:
    """Run records never skip a run. The Notification unique key is bound to the deadline value,
    so moving the Case deadline between two runs with the same occurrence key yields new
    deliveries only if the sweep really executed again (the Action's stay deduplicated)."""
    fixture = _seed_reminder_fixture(postgres_engine)
    key = f"daily:{uuid4()}"
    with Session(postgres_engine) as session, session.begin():  # a crashed earlier run
        session.add(
            SchedulerRunRecord(
                id=uuid4(),
                job_key=JOB_AUTOMATIC_REMINDER_SWEEP,
                occurrence_key=key,
                as_of=NOW,
                started_at=NOW,
                status="running",
            )
        )
    assert _run(factory, fixture.organization_id, key)["created_count"] == 4
    with Session(postgres_engine) as session, session.begin():
        session.execute(
            update(ReviewCaseRecord)
            .where(ReviewCaseRecord.id == fixture.review_case_id)
            .values(planned_end_at=NOW - timedelta(days=2))
        )
    again = _run(factory, fixture.organization_id, key)
    assert again["status"] == "succeeded"
    assert (again["created_count"], again["deduped_count"]) == (2, 2)  # executed, not skipped
    assert _notifications(postgres_engine, fixture.organization_id) == 6


def test_failed_candidate_marks_run_failed_with_safe_summary_and_rerun_completes(
    postgres_engine: Engine,
    factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    key = f"daily:{uuid4()}"
    original = NotificationService.deliver_automatic

    def fail_after_insert(self, **kwargs):  # type: ignore[no-untyped-def]
        outcome = original(self, **kwargs)
        if kwargs["kind"] is NotificationKind.AUTOMATIC_ACTION_REMINDER:
            raise RuntimeError("SECRET-TOKEN INSERT INTO notifications")
        return outcome

    with monkeypatch.context() as patch:
        patch.setattr(NotificationService, "deliver_automatic", fail_after_insert)
        crashed = _run(factory, fixture.organization_id, key)

    assert crashed["status"] == "failed"
    assert crashed["failed_count"] == 1
    assert crashed["created_count"] == 2
    assert crashed["error_summary"] == "failed_candidates=1: RuntimeError x1"
    assert "SECRET" not in json.dumps(crashed)
    row = _rows(postgres_engine, key)[0]
    assert row.status == "failed" and row.error_summary == crashed["error_summary"]

    rerun = _run(factory, fixture.organization_id, key)
    assert rerun["status"] == "succeeded"
    assert (rerun["created_count"], rerun["deduped_count"]) == (2, 2)
    assert _notifications(postgres_engine, fixture.organization_id) == 4  # exactly once each


def test_sweep_that_cannot_run_is_recorded_failed(
    postgres_engine: Engine,
    factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = f"daily:{uuid4()}"

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("password=hunter2")

    monkeypatch.setattr(AutomaticReminderSweep, "_case_candidates", staticmethod(broken))
    outcome = cli.run_reminder_sweep_job(factory, as_of=NOW, occurrence_key=key)
    assert outcome["status"] == "failed"
    assert outcome["error_summary"] == "sweep_aborted: RuntimeError"
    assert [row.status for row in _rows(postgres_engine, key)] == ["failed"]


def test_cli_exit_codes_for_run_and_default_key(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Far in the past: nothing in the shared database is overdue yet, so this run is a no-op.
    monkeypatch.setattr(
        sys, "argv", ["easyaudit-next", "run-reminder-sweep", "--as-of", "2000-01-01T16:30:00Z"]
    )
    with pytest.raises(SystemExit) as ok:
        cli.main()
    assert ok.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["occurrence_key"] == "daily:2000-01-02"  # Shanghai is already the 2nd
    assert out["status"] == "succeeded" and out["scanned_count"] == 0

    def boom(self, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    fixture = _seed_reminder_fixture(postgres_engine)
    monkeypatch.setattr(NotificationService, "deliver_automatic", boom)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "easyaudit-next",
            "run-reminder-sweep",
            "--as-of",
            NOW.isoformat(),
            "--occurrence-key",
            f"cli-{uuid4()}",
        ],
    )
    with pytest.raises(SystemExit) as failed:
        cli.main()
    assert failed.value.code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
    assert _notifications(postgres_engine, fixture.organization_id) == 0


def _add_run(
    engine: Engine,
    job: str,
    *,
    status: str,
    started_at: datetime,
    finished_at: datetime | None,
) -> None:
    with Session(engine) as session, session.begin():
        session.add(
            SchedulerRunRecord(
                id=uuid4(),
                job_key=job,
                occurrence_key=f"daily:{uuid4()}",
                as_of=started_at,
                started_at=started_at,
                finished_at=finished_at,
                status=status,
            )
        )


def _status_exit(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], job: str):
    monkeypatch.setattr(
        sys, "argv", ["easyaudit-next", "scheduler-status", "--job", job, "--max-age-hours", "26"]
    )
    capsys.readouterr()
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    return exit_info.value.code, json.loads(capsys.readouterr().out)


def test_scheduler_status_fresh_stale_failed_never_and_running(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    now = datetime.now(UTC)
    hour = timedelta(hours=1)

    never = f"job_{uuid4().hex[:8]}"
    code, payload = _status_exit(monkeypatch, capsys, never)
    assert code == 1 and payload["reasons"] == ["never_run"] and payload["latest"] is None

    fresh = f"job_{uuid4().hex[:8]}"
    _add_run(
        postgres_engine,
        fresh,
        status="succeeded",
        started_at=now - 2 * hour,
        finished_at=now - hour,
    )
    code, payload = _status_exit(monkeypatch, capsys, fresh)
    assert code == 0 and payload["healthy"] is True
    assert payload["latest"]["status"] == "succeeded"

    stale = f"job_{uuid4().hex[:8]}"
    _add_run(
        postgres_engine,
        stale,
        status="succeeded",
        started_at=now - 28 * hour,
        finished_at=now - 27 * hour,
    )
    code, payload = _status_exit(monkeypatch, capsys, stale)
    assert code == 1 and payload["reasons"] == ["last_success_stale"]

    failed = f"job_{uuid4().hex[:8]}"
    _add_run(
        postgres_engine,
        failed,
        status="succeeded",
        started_at=now - 3 * hour,
        finished_at=now - 2 * hour,
    )
    _add_run(
        postgres_engine, failed, status="failed", started_at=now - hour, finished_at=now - hour
    )
    code, payload = _status_exit(monkeypatch, capsys, failed)
    assert code == 1 and payload["reasons"] == ["latest_run_failed"]
    assert payload["last_succeeded"] is not None

    recovered = f"job_{uuid4().hex[:8]}"
    _add_run(
        postgres_engine,
        recovered,
        status="failed",
        started_at=now - 3 * hour,
        finished_at=now - 3 * hour,
    )
    _add_run(
        postgres_engine,
        recovered,
        status="succeeded",
        started_at=now - hour,
        finished_at=now - hour,
    )
    assert _status_exit(monkeypatch, capsys, recovered)[0] == 0

    crashed = f"job_{uuid4().hex[:8]}"  # latest run died while running; last success still fresh
    _add_run(
        postgres_engine,
        crashed,
        status="succeeded",
        started_at=now - 5 * hour,
        finished_at=now - 4 * hour,
    )
    _add_run(postgres_engine, crashed, status="running", started_at=now - hour, finished_at=None)
    code, payload = _status_exit(monkeypatch, capsys, crashed)
    assert code == 0 and payload["latest"]["status"] == "running"
