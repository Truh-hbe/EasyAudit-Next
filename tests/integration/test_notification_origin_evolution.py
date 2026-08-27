import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from easyaudit_next.composition import (
    build_notification_service,
    build_review_planning_service,
)
from easyaudit_next.notifications.models import (
    NotificationKind,
    NotificationOriginKind,
    ReviewCaseNotificationSubject,
)
from easyaudit_next.notifications.persistence import NotificationRecord
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.domain.ids import ActivityId
from easyaudit_next.review_core.domain.models import ScenarioKey, ScenarioVersion
from easyaudit_next.review_core.persistence.models import ActivityRecord
from tests.integration.notification_test_support import NOW, seed_process_review_users


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _seed_case_with_activity(
    engine: Engine,
) -> tuple[object, object, object, ActivityId]:
    organization_id, _, ids = seed_process_review_users(engine)
    with Session(engine, expire_on_commit=False) as session:
        lead = SqlAlchemyUserRepository(session).get(ids["lead"])
        assert lead is not None
        review_case = build_review_planning_service(session).create_case(
            lead,
            ScenarioKey("process_review"),
            ScenarioVersion(1),
            "Typed Notification origin case",
            {"area_code": "ASSY", "review_type": "routine"},
            occurred_at=NOW,
        )
        activity_id = ActivityId(uuid4())
        session.add(
            ActivityRecord(
                id=activity_id,
                organization_id=organization_id,
                actor_id=lead.id,
                event_type="notification.origin.fixture",
                occurred_at=NOW,
                review_case_id=review_case.id,
                metadata_json={},
            )
        )
        session.commit()
        return organization_id, lead.id, review_case.id, activity_id


def test_automatic_origin_is_idempotent_without_review_activity(
    postgres_engine: Engine,
) -> None:
    organization_id, recipient_id, case_id, _ = _seed_case_with_activity(postgres_engine)
    stable_key = f"case:{case_id}:deadline:2026-08-31T00:00:00Z:overdue:once"

    with Session(postgres_engine) as session, session.begin():
        before_activity_count = session.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(ActivityRecord.organization_id == organization_id)
        )
        service = build_notification_service(session)
        for _ in range(2):
            service.deliver_automatic(
                organization_id=organization_id,
                recipients=(recipient_id, recipient_id),
                kind=NotificationKind.AUTOMATIC_CASE_REMINDER,
                automatic_origin_key=stable_key,
                subject=ReviewCaseNotificationSubject(case_id),
                title="Case deadline reminder",
                body="A ReviewCase deadline needs attention.",
                created_at=NOW,
            )
        after_activity_count = session.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(ActivityRecord.organization_id == organization_id)
        )
        assert after_activity_count == before_activity_count

    with Session(postgres_engine) as session:
        rows = tuple(
            session.scalars(
                select(NotificationRecord).where(
                    NotificationRecord.organization_id == organization_id,
                    NotificationRecord.recipient_user_id == recipient_id,
                    NotificationRecord.kind
                    == NotificationKind.AUTOMATIC_CASE_REMINDER.value,
                    NotificationRecord.automatic_origin_key == stable_key,
                )
            )
        )
        assert len(rows) == 1
        assert rows[0].origin_activity_id is None

        item = next(
            item
            for item in build_notification_service(session)
            .get_inbox(organization_id, recipient_id, limit=100, offset=0)
            .items
            if item.kind is NotificationKind.AUTOMATIC_CASE_REMINDER
        )
        assert item.origin_kind is NotificationOriginKind.AUTOMATIC_REMINDER
        assert item.origin_activity_id is None
        assert item.automatic_origin_key == stable_key


def test_notification_database_requires_exactly_one_origin(
    postgres_engine: Engine,
) -> None:
    organization_id, recipient_id, case_id, activity_id = _seed_case_with_activity(
        postgres_engine
    )

    with pytest.raises(IntegrityError):
        with Session(postgres_engine) as session, session.begin():
            session.add(
                NotificationRecord(
                    id=uuid4(),
                    organization_id=organization_id,
                    recipient_user_id=recipient_id,
                    kind=NotificationKind.AUTOMATIC_CASE_REMINDER.value,
                    origin_activity_id=activity_id,
                    automatic_origin_key="both-origins-are-invalid",
                    review_case_id=case_id,
                    title="Invalid typed origin",
                    body="Invalid",
                    created_at=NOW,
                )
            )
            session.flush()

    with pytest.raises(IntegrityError):
        with Session(postgres_engine) as session, session.begin():
            session.add(
                NotificationRecord(
                    id=uuid4(),
                    organization_id=organization_id,
                    recipient_user_id=recipient_id,
                    kind=NotificationKind.AUTOMATIC_CASE_REMINDER.value,
                    origin_activity_id=None,
                    automatic_origin_key=None,
                    review_case_id=case_id,
                    title="Missing typed origin",
                    body="Invalid",
                    created_at=NOW,
                )
            )
            session.flush()
