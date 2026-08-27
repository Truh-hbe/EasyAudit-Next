import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, func, select, update
from sqlalchemy.orm import Session

from easyaudit_next.composition import (
    build_automatic_reminder_evaluator,
    build_automatic_reminder_sweep,
)
from easyaudit_next.notifications.models import NotificationKind
from easyaudit_next.notifications.persistence import NotificationRecord
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
