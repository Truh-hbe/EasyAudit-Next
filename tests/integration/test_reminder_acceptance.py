import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from time import sleep
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, func, select, text, update
from sqlalchemy.orm import Session

from easyaudit_next.collaboration.automatic_reminder import AutomaticReminderEvaluator
from easyaudit_next.composition import (
    build_automatic_reminder_evaluator,
    build_automatic_reminder_sweep,
)
from easyaudit_next.notifications.models import NotificationKind
from easyaudit_next.notifications.persistence import NotificationRecord
from easyaudit_next.notifications.service import DeliveryOutcome, NotificationService
from easyaudit_next.platform.domain.ids import OrganizationId
from easyaudit_next.review_core.persistence.models import (
    ActionItemRecord,
    ActivityRecord,
    ReviewCaseRecord,
)
from tests.integration.notification_test_support import NOW
from tests.integration.test_automatic_reminder import _seed_reminder_fixture


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _automatic_count(
    session: Session,
    organization_id: OrganizationId,
    kind: NotificationKind,
) -> int:
    count = session.scalar(
        select(func.count())
        .select_from(NotificationRecord)
        .where(
            NotificationRecord.organization_id == organization_id,
            NotificationRecord.kind == kind.value,
        )
    )
    assert count is not None
    return count


def _backend_pid(session: Session) -> int:
    pid = session.scalar(text("SELECT pg_backend_pid()"))
    assert pid is not None
    return int(pid)


def _wait_until_blocked(engine: Engine, backend_pid: int) -> None:
    for _ in range(100):
        with Session(engine) as observer:
            blockers = observer.scalar(
                text("SELECT pg_blocking_pids(:backend_pid)"),
                {"backend_pid": backend_pid},
            )
        if blockers:
            return
        sleep(0.05)
    pytest.fail(f"backend {backend_pid} never became blocked by the target row guard")


def test_case_deadline_pushed_forward_during_resolution_prevents_stale_delivery(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    with Session(postgres_engine) as session:
        evaluator = build_automatic_reminder_evaluator(session)
        original_load = evaluator._recipients.load

        def load_then_move_deadline(
            organization_id: OrganizationId,
            case_id: UUID,
        ):
            snapshot = original_load(organization_id, case_id)
            with Session(postgres_engine) as concurrent, concurrent.begin():
                concurrent.execute(
                    update(ReviewCaseRecord)
                    .where(ReviewCaseRecord.id == case_id)
                    .values(planned_end_at=NOW + timedelta(days=1))
                )
            return snapshot

        monkeypatch.setattr(evaluator._recipients, "load", load_then_move_deadline)
        result = evaluator.evaluate_case_overdue(
            fixture.organization_id,
            fixture.review_case_id,
            occurrence_key="stale-case-deadline",
            as_of=NOW,
        )
        session.commit()

    assert result.eligible is False
    with Session(postgres_engine) as session:
        assert (
            _automatic_count(
                session,
                fixture.organization_id,
                NotificationKind.AUTOMATIC_CASE_REMINDER,
            )
            == 0
        )


def test_action_deadline_cleared_during_resolution_prevents_stale_delivery(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    with Session(postgres_engine) as session:
        evaluator = build_automatic_reminder_evaluator(session)
        original_load = evaluator._recipients.load

        def load_then_clear_deadline(
            organization_id: OrganizationId,
            case_id: UUID,
        ):
            snapshot = original_load(organization_id, case_id)
            with Session(postgres_engine) as concurrent, concurrent.begin():
                concurrent.execute(
                    update(ActionItemRecord)
                    .where(ActionItemRecord.id == fixture.action_item_id)
                    .values(due_at=None)
                )
            return snapshot

        monkeypatch.setattr(evaluator._recipients, "load", load_then_clear_deadline)
        result = evaluator.evaluate_action_overdue(
            fixture.organization_id,
            fixture.action_item_id,
            occurrence_key="stale-action-deadline",
            as_of=NOW,
        )
        session.commit()

    assert result.eligible is False
    with Session(postgres_engine) as session:
        assert (
            _automatic_count(
                session,
                fixture.organization_id,
                NotificationKind.AUTOMATIC_ACTION_REMINDER,
            )
            == 0
        )


def test_case_terminal_mutation_wins_before_final_guard_prevents_delivery(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    mutation_has_lock = Event()
    release_mutation = Event()
    guard_attempted = Event()
    reminder_backend_pid: list[int] = []
    original_load = AutomaticReminderEvaluator._load_case

    def traced_load(
        evaluator: AutomaticReminderEvaluator,
        organization_id: OrganizationId,
        review_case_id: UUID,
        *,
        guard: bool = False,
    ):
        if guard:
            reminder_backend_pid.append(_backend_pid(evaluator._session))
            guard_attempted.set()
        return original_load(
            evaluator,
            organization_id,
            review_case_id,
            guard=guard,
        )

    monkeypatch.setattr(AutomaticReminderEvaluator, "_load_case", traced_load)

    def terminalize_first() -> None:
        with Session(postgres_engine) as concurrent:
            concurrent.execute(
                update(ReviewCaseRecord)
                .where(ReviewCaseRecord.id == fixture.review_case_id)
                .values(lifecycle="closed")
            )
            mutation_has_lock.set()
            assert release_mutation.wait(timeout=5)
            concurrent.commit()

    def evaluate() -> object:
        with Session(postgres_engine) as session:
            result = build_automatic_reminder_evaluator(session).evaluate_case_overdue(
                fixture.organization_id,
                fixture.review_case_id,
                occurrence_key="case-mutation-wins-final-guard",
                as_of=NOW,
            )
            session.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        mutation = executor.submit(terminalize_first)
        assert mutation_has_lock.wait(timeout=5)
        reminder = executor.submit(evaluate)
        assert guard_attempted.wait(timeout=5)
        assert reminder_backend_pid
        _wait_until_blocked(postgres_engine, reminder_backend_pid[0])
        release_mutation.set()
        mutation.result(timeout=10)
        result = reminder.result(timeout=10)

    assert result.eligible is False
    with Session(postgres_engine) as session:
        assert (
            _automatic_count(
                session,
                fixture.organization_id,
                NotificationKind.AUTOMATIC_CASE_REMINDER,
            )
            == 0
        )


def test_action_terminal_mutation_wins_before_final_guard_prevents_delivery(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    mutation_has_lock = Event()
    release_mutation = Event()
    guard_attempted = Event()
    reminder_backend_pid: list[int] = []
    original_load = AutomaticReminderEvaluator._load_action

    def traced_load(
        evaluator: AutomaticReminderEvaluator,
        organization_id: OrganizationId,
        action_item_id: UUID,
        *,
        guard: bool = False,
    ):
        if guard:
            reminder_backend_pid.append(_backend_pid(evaluator._session))
            guard_attempted.set()
        return original_load(
            evaluator,
            organization_id,
            action_item_id,
            guard=guard,
        )

    monkeypatch.setattr(AutomaticReminderEvaluator, "_load_action", traced_load)

    def terminalize_first() -> None:
        with Session(postgres_engine) as concurrent:
            concurrent.execute(
                update(ActionItemRecord)
                .where(ActionItemRecord.id == fixture.action_item_id)
                .values(lifecycle="done")
            )
            mutation_has_lock.set()
            assert release_mutation.wait(timeout=5)
            concurrent.commit()

    def evaluate() -> object:
        with Session(postgres_engine) as session:
            result = build_automatic_reminder_evaluator(session).evaluate_action_overdue(
                fixture.organization_id,
                fixture.action_item_id,
                occurrence_key="action-mutation-wins-final-guard",
                as_of=NOW,
            )
            session.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        mutation = executor.submit(terminalize_first)
        assert mutation_has_lock.wait(timeout=5)
        reminder = executor.submit(evaluate)
        assert guard_attempted.wait(timeout=5)
        assert reminder_backend_pid
        _wait_until_blocked(postgres_engine, reminder_backend_pid[0])
        release_mutation.set()
        mutation.result(timeout=10)
        result = reminder.result(timeout=10)

    assert result.eligible is False
    with Session(postgres_engine) as session:
        assert (
            _automatic_count(
                session,
                fixture.organization_id,
                NotificationKind.AUTOMATIC_ACTION_REMINDER,
            )
            == 0
        )


def test_case_final_guard_wins_before_deadline_push_serializes_delivery_first(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    guard_held = Event()
    release_delivery = Event()
    mutation_ready = Event()
    mutation_backend_pid: list[int] = []
    original_deliver = NotificationService.deliver_automatic

    def block_delivery(service: NotificationService, **kwargs: object) -> DeliveryOutcome:
        guard_held.set()
        assert release_delivery.wait(timeout=5)
        return original_deliver(service, **kwargs)

    monkeypatch.setattr(NotificationService, "deliver_automatic", block_delivery)

    def evaluate() -> object:
        with Session(postgres_engine) as session:
            result = build_automatic_reminder_evaluator(session).evaluate_case_overdue(
                fixture.organization_id,
                fixture.review_case_id,
                occurrence_key="case-reminder-wins-final-guard",
                as_of=NOW,
            )
            session.commit()
            return result

    def push_deadline() -> None:
        with Session(postgres_engine) as concurrent:
            mutation_backend_pid.append(_backend_pid(concurrent))
            mutation_ready.set()
            concurrent.execute(
                update(ReviewCaseRecord)
                .where(ReviewCaseRecord.id == fixture.review_case_id)
                .values(planned_end_at=NOW + timedelta(days=1))
            )
            concurrent.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        reminder = executor.submit(evaluate)
        assert guard_held.wait(timeout=5)
        mutation = executor.submit(push_deadline)
        assert mutation_ready.wait(timeout=5)
        assert mutation_backend_pid
        _wait_until_blocked(postgres_engine, mutation_backend_pid[0])
        release_delivery.set()
        result = reminder.result(timeout=10)
        mutation.result(timeout=10)

    assert result.eligible is True
    with Session(postgres_engine) as session:
        assert (
            _automatic_count(
                session,
                fixture.organization_id,
                NotificationKind.AUTOMATIC_CASE_REMINDER,
            )
            == 2
        )
        deadline = session.scalar(
            select(ReviewCaseRecord.planned_end_at).where(
                ReviewCaseRecord.id == fixture.review_case_id
            )
        )
        assert deadline == NOW + timedelta(days=1)


def test_action_final_guard_wins_before_deadline_clear_serializes_delivery_first(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    guard_held = Event()
    release_delivery = Event()
    mutation_ready = Event()
    mutation_backend_pid: list[int] = []
    original_deliver = NotificationService.deliver_automatic

    def block_delivery(service: NotificationService, **kwargs: object) -> DeliveryOutcome:
        guard_held.set()
        assert release_delivery.wait(timeout=5)
        return original_deliver(service, **kwargs)

    monkeypatch.setattr(NotificationService, "deliver_automatic", block_delivery)

    def evaluate() -> object:
        with Session(postgres_engine) as session:
            result = build_automatic_reminder_evaluator(session).evaluate_action_overdue(
                fixture.organization_id,
                fixture.action_item_id,
                occurrence_key="action-reminder-wins-final-guard",
                as_of=NOW,
            )
            session.commit()
            return result

    def clear_deadline() -> None:
        with Session(postgres_engine) as concurrent:
            mutation_backend_pid.append(_backend_pid(concurrent))
            mutation_ready.set()
            concurrent.execute(
                update(ActionItemRecord)
                .where(ActionItemRecord.id == fixture.action_item_id)
                .values(due_at=None)
            )
            concurrent.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        reminder = executor.submit(evaluate)
        assert guard_held.wait(timeout=5)
        mutation = executor.submit(clear_deadline)
        assert mutation_ready.wait(timeout=5)
        assert mutation_backend_pid
        _wait_until_blocked(postgres_engine, mutation_backend_pid[0])
        release_delivery.set()
        result = reminder.result(timeout=10)
        mutation.result(timeout=10)

    assert result.eligible is True
    with Session(postgres_engine) as session:
        assert (
            _automatic_count(
                session,
                fixture.organization_id,
                NotificationKind.AUTOMATIC_ACTION_REMINDER,
            )
            == 2
        )
        due_at = session.scalar(
            select(ActionItemRecord.due_at).where(
                ActionItemRecord.id == fixture.action_item_id
            )
        )
        assert due_at is None


def test_successful_automatic_evaluation_changes_no_review_lifecycle_or_activity(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    with Session(postgres_engine) as session:
        before_case = session.scalar(
            select(ReviewCaseRecord.lifecycle).where(
                ReviewCaseRecord.id == fixture.review_case_id
            )
        )
        before_action = session.scalar(
            select(ActionItemRecord.lifecycle).where(
                ActionItemRecord.id == fixture.action_item_id
            )
        )
        before_activity_count = session.scalar(select(func.count()).select_from(ActivityRecord))
        evaluator = build_automatic_reminder_evaluator(session)
        evaluator.evaluate_case_overdue(
            fixture.organization_id,
            fixture.review_case_id,
            occurrence_key="no-lifecycle-side-effect-case",
            as_of=NOW,
        )
        evaluator.evaluate_action_overdue(
            fixture.organization_id,
            fixture.action_item_id,
            occurrence_key="no-lifecycle-side-effect-action",
            as_of=NOW,
        )
        session.commit()

    with Session(postgres_engine) as session:
        after_case = session.scalar(
            select(ReviewCaseRecord.lifecycle).where(
                ReviewCaseRecord.id == fixture.review_case_id
            )
        )
        after_action = session.scalar(
            select(ActionItemRecord.lifecycle).where(
                ActionItemRecord.id == fixture.action_item_id
            )
        )
        after_activity_count = session.scalar(select(func.count()).select_from(ActivityRecord))
        assert after_case == before_case
        assert after_action == before_action
        assert after_activity_count == before_activity_count


def test_concurrent_sweeps_same_occurrence_commit_one_logical_delivery_per_recipient(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    barrier = Barrier(2)

    def run_once() -> None:
        with Session(postgres_engine) as session:
            barrier.wait()
            build_automatic_reminder_sweep(session).run_once(
                occurrence_key="concurrent-sweep-occurrence",
                as_of=NOW,
                organization_id=fixture.organization_id,
                batch_size=1,
            )
            session.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run_once) for _ in range(2)]
        for future in futures:
            future.result(timeout=10)

    with Session(postgres_engine) as session:
        assert (
            _automatic_count(
                session,
                fixture.organization_id,
                NotificationKind.AUTOMATIC_CASE_REMINDER,
            )
            == 2
        )
        assert (
            _automatic_count(
                session,
                fixture.organization_id,
                NotificationKind.AUTOMATIC_ACTION_REMINDER,
            )
            == 2
        )
        origin_keys = set(
            session.scalars(
                select(NotificationRecord.automatic_origin_key).where(
                    NotificationRecord.organization_id == fixture.organization_id,
                    NotificationRecord.kind.in_(
                        (
                            NotificationKind.AUTOMATIC_CASE_REMINDER.value,
                            NotificationKind.AUTOMATIC_ACTION_REMINDER.value,
                        )
                    ),
                )
            )
        )
        assert None not in origin_keys
        assert len(origin_keys) == 2
