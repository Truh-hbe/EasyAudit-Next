import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, delete, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from easyaudit_next.composition import build_notification_service
from easyaudit_next.notifications.copy import COPY
from easyaudit_next.notifications.models import (
    NotificationKind,
    ReviewCaseNotificationSubject,
)
from easyaudit_next.notifications.persistence import NotificationRecord
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.persistence.models import OrganizationRecord, UserRecord
from easyaudit_next.review_core.domain.ids import ActivityId, ReviewCaseId
from easyaudit_next.review_core.persistence.models import (
    ActivityRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)

NOW = datetime(2026, 8, 27, 15, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _seed_delivery_context(
    engine: Engine,
) -> tuple[OrganizationId, UserId, UserId, ReviewCaseId, ActivityId]:
    organization_id = OrganizationId(uuid4())
    recipient_id = UserId(uuid4())
    other_user_id = UserId(uuid4())
    scenario_id = uuid4()
    scenario_version_id = uuid4()
    review_case_id = ReviewCaseId(uuid4())
    activity_id = ActivityId(uuid4())

    with Session(engine) as session, session.begin():
        session.add(
            OrganizationRecord(
                id=organization_id,
                name=f"Notification persistence {organization_id}",
            )
        )
        session.flush()
        session.add_all(
            [
                UserRecord(
                    id=recipient_id,
                    organization_id=organization_id,
                    display_name="Notification Recipient",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=other_user_id,
                    organization_id=organization_id,
                    display_name="Other User",
                    platform_role="ordinary_user",
                ),
            ]
        )
        session.flush()
        session.add(
            ScenarioRecord(
                id=scenario_id,
                organization_id=organization_id,
                key=f"notification_test_{uuid4().hex}",
                name="Notification Test Scenario",
            )
        )
        session.flush()
        session.add(
            ScenarioVersionRecord(
                id=scenario_version_id,
                scenario_id=scenario_id,
                organization_id=organization_id,
                version=1,
                published_at=NOW,
            )
        )
        session.flush()
        session.add(
            ReviewCaseRecord(
                id=review_case_id,
                organization_id=organization_id,
                scenario_version_id=scenario_version_id,
                title="Notification persistence case",
                lifecycle="draft",
                scenario_data_json={},
                created_by=recipient_id,
                created_at=NOW,
            )
        )
        session.flush()
        session.add(
            ActivityRecord(
                id=activity_id,
                organization_id=organization_id,
                actor_id=recipient_id,
                event_type="review_case.member_added",
                occurred_at=NOW,
                review_case_id=review_case_id,
                metadata_json={"user_id": str(recipient_id), "role_key": "observer"},
            )
        )
    return organization_id, recipient_id, other_user_id, review_case_id, activity_id


def _deliver_case_membership(
    session: Session,
    organization_id: OrganizationId,
    recipient_id: UserId,
    review_case_id: ReviewCaseId,
    activity_id: ActivityId,
    *,
    created_at: datetime = NOW,
) -> None:
    build_notification_service(session).deliver(
        organization_id=organization_id,
        recipients=(recipient_id,),
        kind=NotificationKind.CASE_MEMBERSHIP_ADDED,
        origin_activity_id=activity_id,
        subject=ReviewCaseNotificationSubject(review_case_id),
        title="ReviewCase membership added",
        body="You were added to a ReviewCase.",
        created_at=created_at,
    )


def test_duplicate_delivery_uses_atomic_conflict_handling_without_poisoning_transaction(
    postgres_engine: Engine,
) -> None:
    organization_id, recipient_id, _, review_case_id, activity_id = _seed_delivery_context(
        postgres_engine
    )
    additional_user_id = UserId(uuid4())

    with Session(postgres_engine) as session, session.begin():
        _deliver_case_membership(
            session,
            organization_id,
            recipient_id,
            review_case_id,
            activity_id,
        )
        _deliver_case_membership(
            session,
            organization_id,
            recipient_id,
            review_case_id,
            activity_id,
        )
        session.add(
            UserRecord(
                id=additional_user_id,
                organization_id=organization_id,
                display_name="Transaction remains usable",
                platform_role="ordinary_user",
            )
        )
        session.flush()

        count = session.scalar(
            select(func.count())
            .select_from(NotificationRecord)
            .where(
                NotificationRecord.organization_id == organization_id,
                NotificationRecord.recipient_user_id == recipient_id,
                NotificationRecord.origin_activity_id == activity_id,
                NotificationRecord.kind == NotificationKind.CASE_MEMBERSHIP_ADDED.value,
            )
        )
        assert count == 1


def test_concurrent_duplicate_delivery_commits_one_logical_notification(
    postgres_engine: Engine,
) -> None:
    organization_id, recipient_id, _, review_case_id, activity_id = _seed_delivery_context(
        postgres_engine
    )
    barrier = Barrier(2)

    def deliver_once() -> None:
        with Session(postgres_engine) as session:
            barrier.wait()
            _deliver_case_membership(
                session,
                organization_id,
                recipient_id,
                review_case_id,
                activity_id,
            )
            session.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(deliver_once) for _ in range(2)]
        for future in futures:
            future.result(timeout=10)

    with Session(postgres_engine) as verification:
        count = verification.scalar(
            select(func.count())
            .select_from(NotificationRecord)
            .where(
                NotificationRecord.organization_id == organization_id,
                NotificationRecord.recipient_user_id == recipient_id,
                NotificationRecord.origin_activity_id == activity_id,
                NotificationRecord.kind == NotificationKind.CASE_MEMBERSHIP_ADDED.value,
            )
        )
        assert count == 1


def test_origin_activity_must_belong_to_notification_organization(
    postgres_engine: Engine,
) -> None:
    org_a, _, _, _, activity_a = _seed_delivery_context(postgres_engine)
    org_b, recipient_b, _, case_b, _ = _seed_delivery_context(postgres_engine)
    assert org_a != org_b

    with pytest.raises(IntegrityError):
        with Session(postgres_engine) as session, session.begin():
            _deliver_case_membership(
                session,
                org_b,
                recipient_b,
                case_b,
                activity_a,
            )


def test_read_at_is_idempotent_and_delivery_facts_are_database_immutable(
    postgres_engine: Engine,
) -> None:
    organization_id, recipient_id, other_user_id, review_case_id, activity_id = (
        _seed_delivery_context(postgres_engine)
    )

    with Session(postgres_engine) as session, session.begin():
        _deliver_case_membership(
            session,
            organization_id,
            recipient_id,
            review_case_id,
            activity_id,
        )
        notification_id = session.scalar(
            select(NotificationRecord.id).where(
                NotificationRecord.organization_id == organization_id,
                NotificationRecord.recipient_user_id == recipient_id,
                NotificationRecord.origin_activity_id == activity_id,
            )
        )
        assert notification_id is not None

    with Session(postgres_engine) as session, session.begin():
        service = build_notification_service(session)
        with pytest.raises(LookupError, match="Notification not found"):
            service.mark_read(organization_id, other_user_id, notification_id)
        first = service.mark_read(organization_id, recipient_id, notification_id)
        assert first.read_at is not None
        first_read_at = first.read_at

    with Session(postgres_engine) as session, session.begin():
        second = build_notification_service(session).mark_read(
            organization_id,
            recipient_id,
            notification_id,
        )
        assert second.read_at == first_read_at

    with pytest.raises(DBAPIError):
        with Session(postgres_engine) as session, session.begin():
            session.execute(
                update(NotificationRecord)
                .where(NotificationRecord.id == notification_id)
                .values(title="Rewritten delivery fact")
            )

    with pytest.raises(DBAPIError):
        with Session(postgres_engine) as session, session.begin():
            session.execute(
                delete(NotificationRecord).where(NotificationRecord.id == notification_id)
            )


def test_inbox_is_bounded_newest_first_and_unread_count_is_recipient_local(
    postgres_engine: Engine,
) -> None:
    organization_id, recipient_id, other_user_id, review_case_id, first_activity_id = (
        _seed_delivery_context(postgres_engine)
    )
    second_activity_id = ActivityId(uuid4())

    with Session(postgres_engine) as session, session.begin():
        session.add(
            ActivityRecord(
                id=second_activity_id,
                organization_id=organization_id,
                actor_id=recipient_id,
                event_type="review_case.member_added",
                occurred_at=NOW + timedelta(seconds=1),
                review_case_id=review_case_id,
                metadata_json={"user_id": str(recipient_id), "role_key": "observer"},
            )
        )
        session.flush()
        _deliver_case_membership(
            session,
            organization_id,
            recipient_id,
            review_case_id,
            first_activity_id,
            created_at=NOW,
        )
        _deliver_case_membership(
            session,
            organization_id,
            recipient_id,
            review_case_id,
            second_activity_id,
            created_at=NOW + timedelta(seconds=1),
        )

    with Session(postgres_engine) as session:
        service = build_notification_service(session)
        page = service.get_inbox(
            organization_id,
            recipient_id,
            limit=1,
            offset=0,
        )
        other_page = service.get_inbox(
            organization_id,
            other_user_id,
            limit=100,
            offset=0,
        )

        assert len(page.items) == 1
        assert page.items[0].origin_activity_id == second_activity_id
        assert page.unread_count == 2
        assert other_page.items == ()
        assert other_page.unread_count == 0


def test_inbox_upgrades_legacy_english_rows_and_new_rows_store_chinese(
    postgres_engine: Engine,
) -> None:
    organization_id, recipient_id, _, review_case_id, activity_id = _seed_delivery_context(
        postgres_engine
    )
    new_activity_id = ActivityId(uuid4())
    with Session(postgres_engine) as session, session.begin():
        session.add(
            ActivityRecord(
                id=new_activity_id,
                organization_id=organization_id,
                actor_id=recipient_id,
                event_type="review_case.member_added",
                occurred_at=NOW,
                review_case_id=review_case_id,
                metadata_json={"user_id": str(recipient_id), "role_key": "observer"},
            )
        )
        # Legacy English row, as written before the Chinese copy shipped.
        _deliver_case_membership(
            session, organization_id, recipient_id, review_case_id, activity_id
        )
        build_notification_service(session).deliver(
            organization_id=organization_id,
            recipients=(recipient_id,),
            kind=NotificationKind.CASE_MEMBERSHIP_ADDED,
            origin_activity_id=new_activity_id,
            subject=ReviewCaseNotificationSubject(review_case_id),
            title=COPY[NotificationKind.CASE_MEMBERSHIP_ADDED].title,
            body=COPY[NotificationKind.CASE_MEMBERSHIP_ADDED].body,
            created_at=NOW + timedelta(minutes=1),
        )

    with Session(postgres_engine) as session:
        page = build_notification_service(session).get_inbox(
            organization_id, recipient_id, limit=10, offset=0
        )
        stored = {
            row.origin_activity_id: (row.title, row.body)
            for row in session.scalars(
                select(NotificationRecord).where(
                    NotificationRecord.organization_id == organization_id
                )
            )
        }

    expected = COPY[NotificationKind.CASE_MEMBERSHIP_ADDED]
    assert [(i.title, i.body) for i in page.items] == [(expected.title, expected.body)] * 2
    assert stored[activity_id] == ("ReviewCase membership added", "You were added to a ReviewCase.")
    assert stored[new_activity_id] == (expected.title, expected.body)
