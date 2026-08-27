import os
from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy import Engine, create_engine, func, select, update
from sqlalchemy.orm import Session

from easyaudit_next.composition import build_automatic_reminder_sweep
from easyaudit_next.notifications.models import NotificationKind
from easyaudit_next.notifications.persistence import NotificationRecord
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


def _automatic_count(session: Session, organization_id) -> int:
    count = session.scalar(
        select(func.count())
        .select_from(NotificationRecord)
        .where(
            NotificationRecord.organization_id == organization_id,
            NotificationRecord.kind.in_(
                (
                    NotificationKind.AUTOMATIC_CASE_REMINDER.value,
                    NotificationKind.AUTOMATIC_ACTION_REMINDER.value,
                )
            ),
        )
    )
    assert count is not None
    return count


def test_one_shot_sweep_discovers_case_and_action_without_creating_activity(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    with Session(postgres_engine) as session:
        before_activity_count = session.scalar(select(func.count()).select_from(ActivityRecord))
        result = build_automatic_reminder_sweep(session).run_once(
            occurrence_key="sweep-occurrence-2026-08-27",
            as_of=NOW,
            organization_id=fixture.organization_id,
            batch_size=1,
        )
        session.commit()

    with Session(postgres_engine) as session:
        after_activity_count = session.scalar(select(func.count()).select_from(ActivityRecord))
        assert before_activity_count == after_activity_count
        assert result.case_candidates == 1
        assert result.action_candidates == 1
        assert result.eligible_cases == 1
        assert result.eligible_actions == 1
        assert result.recipient_deliveries_evaluated == 4
        assert _automatic_count(session, fixture.organization_id) == 4


def test_repeated_sweep_with_same_occurrence_is_idempotent_at_notification_boundary(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    with Session(postgres_engine) as session:
        sweep = build_automatic_reminder_sweep(session)
        first = sweep.run_once(
            occurrence_key="repeated-sweep-occurrence",
            as_of=NOW,
            organization_id=fixture.organization_id,
            batch_size=1,
        )
        session.commit()

    with Session(postgres_engine) as session:
        sweep = build_automatic_reminder_sweep(session)
        second = sweep.run_once(
            occurrence_key="repeated-sweep-occurrence",
            as_of=NOW,
            organization_id=fixture.organization_id,
            batch_size=1,
        )
        session.commit()

    assert first.case_candidates == second.case_candidates == 1
    assert first.action_candidates == second.action_candidates == 1
    with Session(postgres_engine) as session:
        assert _automatic_count(session, fixture.organization_id) == 4


def test_sweep_coarse_discovery_excludes_null_future_and_terminal_deadlines(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    with Session(postgres_engine) as session, session.begin():
        session.execute(
            update(ReviewCaseRecord)
            .where(ReviewCaseRecord.id == fixture.review_case_id)
            .values(planned_end_at=None)
        )
        session.execute(
            update(ActionItemRecord)
            .where(ActionItemRecord.id == fixture.action_item_id)
            .values(due_at=NOW + timedelta(days=1), lifecycle="done")
        )

    with Session(postgres_engine) as session:
        result = build_automatic_reminder_sweep(session).run_once(
            occurrence_key="no-candidates-sweep",
            as_of=NOW,
            organization_id=fixture.organization_id,
            batch_size=1,
        )
        session.commit()

    assert result.case_candidates == 0
    assert result.action_candidates == 0
    assert result.eligible_cases == 0
    assert result.eligible_actions == 0
    assert result.recipient_deliveries_evaluated == 0


def test_sweep_requires_explicit_stable_occurrence_and_bounded_batch_size(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine) as session:
        sweep = build_automatic_reminder_sweep(session)
        with pytest.raises(ValueError, match="occurrence key"):
            sweep.run_once(occurrence_key=" ", as_of=NOW)
        with pytest.raises(ValueError, match="batch_size"):
            sweep.run_once(occurrence_key="valid", as_of=NOW, batch_size=0)
