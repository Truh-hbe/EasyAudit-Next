"""Per-candidate transactions: counts, failure isolation and rerun idempotency (real PostgreSQL)."""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from easyaudit_next.composition import (
    build_automatic_reminder_sweep,
    build_per_candidate_reminder_sweep,
)
from easyaudit_next.notifications.models import NotificationKind
from easyaudit_next.notifications.persistence import NotificationRecord
from easyaudit_next.notifications.service import NotificationService
from tests.integration.notification_test_support import NOW
from tests.integration.test_automatic_reminder import _seed_reminder_fixture

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


def _count(engine: Engine, organization_id, kind: str | None = None) -> int:
    with Session(engine) as session:
        statement = (
            select(func.count())
            .select_from(NotificationRecord)
            .where(
                NotificationRecord.organization_id == organization_id,
                NotificationRecord.kind.in_(AUTOMATIC_KINDS if kind is None else (kind,)),
            )
        )
        return session.scalar(statement) or 0


def test_counts_created_then_deduped_on_second_run_with_same_key(postgres_engine: Engine) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    factory = sessionmaker(postgres_engine, autoflush=False, expire_on_commit=False)
    runs = [
        build_per_candidate_reminder_sweep(factory).run_once(
            occurrence_key="daily:2026-10-02",
            as_of=NOW,
            organization_id=fixture.organization_id,
            batch_size=1,
        )
        for _ in range(2)
    ]
    first, second = runs
    assert first.case_candidates + first.action_candidates == 2
    assert first.created_deliveries == 4 == first.recipient_deliveries_evaluated
    assert first.deduped_deliveries == 0
    assert second.created_deliveries == 0
    assert second.deduped_deliveries == first.created_deliveries
    assert first.failed_candidates == second.failed_candidates == 0
    assert _count(postgres_engine, fixture.organization_id) == 4


def test_failure_in_one_candidate_rolls_back_only_that_candidate_and_rerun_completes(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    factory = sessionmaker(postgres_engine, autoflush=False, expire_on_commit=False)
    original = NotificationService.deliver_automatic

    def fail_after_insert(self, **kwargs):  # type: ignore[no-untyped-def]
        outcome = original(self, **kwargs)
        if kwargs["kind"] is NotificationKind.AUTOMATIC_ACTION_REMINDER:
            raise RuntimeError("secret sql parameters must not leak")
        return outcome

    with monkeypatch.context() as patch:
        patch.setattr(NotificationService, "deliver_automatic", fail_after_insert)
        crashed = build_per_candidate_reminder_sweep(factory).run_once(
            occurrence_key="daily:2026-10-02",
            as_of=NOW,
            organization_id=fixture.organization_id,
        )

    assert crashed.failed_candidates == 1
    assert crashed.failure_types == (("RuntimeError", 1),)
    assert crashed.created_deliveries == 2  # the Case candidate committed before the failure
    case_kind = NotificationKind.AUTOMATIC_CASE_REMINDER.value
    action_kind = NotificationKind.AUTOMATIC_ACTION_REMINDER.value
    assert _count(postgres_engine, fixture.organization_id, case_kind) == 2
    assert _count(postgres_engine, fixture.organization_id, action_kind) == 0  # rolled back

    rerun = build_per_candidate_reminder_sweep(factory).run_once(
        occurrence_key="daily:2026-10-02",
        as_of=NOW,
        organization_id=fixture.organization_id,
    )
    assert rerun.failed_candidates == 0
    assert rerun.created_deliveries == 2
    assert rerun.deduped_deliveries == 2
    assert _count(postgres_engine, fixture.organization_id, case_kind) == 2
    assert _count(postgres_engine, fixture.organization_id, action_kind) == 2


def test_in_caller_transaction_mode_still_propagates_failures(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)

    def boom(self, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    monkeypatch.setattr(NotificationService, "deliver_automatic", boom)
    with Session(postgres_engine) as session, pytest.raises(RuntimeError):
        build_automatic_reminder_sweep(session).run_once(
            occurrence_key="legacy", as_of=NOW, organization_id=fixture.organization_id
        )
