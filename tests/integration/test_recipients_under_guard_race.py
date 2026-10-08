"""Reminder and nudge recipients come from facts read under the Case guard lock (PostgreSQL).

- the automatic reminder takes the Case lock (Case before Action) and only then resolves
  recipients, so a team/assignee change that commits while it waits is honoured;
- `RecipientResolver.load` refreshes rows already in the Session's identity map, so the
  manual nudge's post-lock read does not reuse the authorization-stage snapshot.
"""

import os
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, delete, select, text, update
from sqlalchemy.orm import Session

from easyaudit_next.composition import (
    build_automatic_reminder_evaluator,
    build_manual_nudge_service,
)
from easyaudit_next.notifications.models import NotificationKind
from easyaudit_next.notifications.persistence import NotificationRecord
from easyaudit_next.platform.domain.ids import UserId
from easyaudit_next.platform.persistence.models import UserRecord
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.persistence.models import (
    ActionAssigneeRecord,
    CaseMemberRecord,
    FindingRecord,
    ReviewCaseRecord,
)
from tests.integration.notification_test_support import NOW
from tests.integration.test_automatic_reminder import ReminderFixture, _seed_reminder_fixture
from tests.integration.test_manual_nudge import _seed_nudge_fixture

WAIT = 15


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _wait_blocked_by(engine: Engine, blocker_pid: int) -> str:
    """Statement of the session waiting on `blocker_pid` (never a fixed sleep)."""
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT query FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                    "AND :pid = ANY(pg_blocking_pids(pid))"
                ),
                {"pid": blocker_pid},
            ).first()
        if row is not None:
            return str(row[0])
        time.sleep(0.05)
    raise AssertionError("evaluation never waited on the Case lock")


def _recipients(
    engine: Engine, fixture: ReminderFixture, kind: NotificationKind
) -> set[UUID]:
    with Session(engine) as session:
        return {
            row.recipient_user_id
            for row in session.scalars(
                select(NotificationRecord).where(
                    NotificationRecord.organization_id == fixture.organization_id,
                    NotificationRecord.kind == kind.value,
                )
            )
        }


def test_case_reminder_resolves_recipients_after_waiting_for_the_case_lock(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    with Session(postgres_engine) as web, web.begin():
        web_pid = web.scalar(text("SELECT pg_backend_pid()"))
        web.execute(
            select(ReviewCaseRecord.id)
            .where(ReviewCaseRecord.id == fixture.review_case_id)
            .with_for_update(key_share=True)
        )

        def evaluate():  # type: ignore[no-untyped-def]
            with Session(postgres_engine) as session:
                result = build_automatic_reminder_evaluator(session).evaluate_case_overdue(
                    fixture.organization_id,
                    fixture.review_case_id,
                    occurrence_key="guard-case",
                    as_of=NOW,
                )
                session.commit()
                return result

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(evaluate)
            waiting = _wait_blocked_by(postgres_engine, web_pid)
            assert "FROM review_cases" in waiting and "FOR NO KEY UPDATE" in waiting, waiting
            web.execute(
                delete(CaseMemberRecord).where(
                    CaseMemberRecord.case_id == fixture.review_case_id,
                    CaseMemberRecord.user_id == fixture.second_lead_id,
                )
            )
            web.commit()
            result = future.result(WAIT)

    assert result.eligible and result.recipient_count == 1
    assert _recipients(
        postgres_engine, fixture, NotificationKind.AUTOMATIC_CASE_REMINDER
    ) == {fixture.lead_id}


def test_action_reminder_locks_the_case_before_resolving_recipients(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    with Session(postgres_engine) as web, web.begin():
        web_pid = web.scalar(text("SELECT pg_backend_pid()"))
        web.execute(
            select(ReviewCaseRecord.id)
            .where(ReviewCaseRecord.id == fixture.review_case_id)
            .with_for_update(key_share=True)
        )

        def evaluate():  # type: ignore[no-untyped-def]
            with Session(postgres_engine) as session:
                result = build_automatic_reminder_evaluator(session).evaluate_action_overdue(
                    fixture.organization_id,
                    fixture.action_item_id,
                    occurrence_key="guard-action",
                    as_of=NOW,
                )
                session.commit()
                return result

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(evaluate)
            waiting = _wait_blocked_by(postgres_engine, web_pid)
            # queued on the Case row, not on the Action row: Case before Action
            assert "FROM review_cases" in waiting and "FOR NO KEY UPDATE" in waiting, waiting
            web.execute(
                delete(ActionAssigneeRecord).where(
                    ActionAssigneeRecord.action_item_id == fixture.action_item_id,
                    ActionAssigneeRecord.user_id == fixture.action_collaborator_id,
                )
            )
            web.commit()
            result = future.result(WAIT)

    assert result.eligible and result.recipient_count == 1
    assert _recipients(
        postgres_engine, fixture, NotificationKind.AUTOMATIC_ACTION_REMINDER
    ) == {fixture.action_assignee_id}


def test_manual_nudge_recipients_ignore_the_authorization_stage_snapshot(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_nudge_fixture(postgres_engine)
    with Session(postgres_engine) as lookup:
        replacement = lookup.scalar(
            select(UserRecord.id).where(
                UserRecord.organization_id == fixture.organization_id,
                UserRecord.display_name == "Unrelated",
            )
        )
        case_id = lookup.scalar(
            select(FindingRecord.case_id).where(FindingRecord.id == fixture.finding_id)
        )
    assert replacement is not None and case_id is not None

    with Session(postgres_engine, expire_on_commit=False) as session:
        lead = SqlAlchemyUserRepository(session).get(fixture.lead_id)
        assert lead is not None
        service = build_manual_nudge_service(session)
        # Authorization stage: the assignee row sits in this Session's identity map. The
        # identity map holds weak references, so keep one the way a live caller would.
        service._recipients.load(fixture.organization_id, case_id)
        held = session.scalars(
            select(ActionAssigneeRecord).where(
                ActionAssigneeRecord.action_item_id == fixture.action_item_id
            )
        ).all()
        assert [row.user_id for row in held] == [fixture.assignee_id]

        with Session(postgres_engine) as other, other.begin():
            other.execute(
                update(ActionAssigneeRecord)
                .where(ActionAssigneeRecord.action_item_id == fixture.action_item_id)
                .values(user_id=replacement)
            )

        result = service.nudge_action_item(lead, fixture.action_item_id, occurred_at=NOW)
        session.commit()

    assert result.recipient_count == 1
    with Session(postgres_engine) as session:
        recipients = {
            row.recipient_user_id
            for row in session.scalars(
                select(NotificationRecord).where(
                    NotificationRecord.origin_activity_id == result.activity_id
                )
            )
        }
    assert recipients == {UserId(replacement)}
    assert held  # referenced until here, so the stale row really was in the identity map
