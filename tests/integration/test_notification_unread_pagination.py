import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from easyaudit_next.composition import build_notification_service
from easyaudit_next.notifications.models import NotificationKind, ReviewCaseNotificationSubject
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

NOW = datetime(2026, 8, 28, 16, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _seed_inbox(engine: Engine) -> tuple[OrganizationId, UserId, dict[str, ActivityId]]:
    organization_id = OrganizationId(uuid4())
    recipient_id = UserId(uuid4())
    other_user_id = UserId(uuid4())
    scenario_id = uuid4()
    scenario_version_id = uuid4()
    case_id = ReviewCaseId(uuid4())
    activity_ids = {
        name: ActivityId(uuid4())
        for name in ("U1", "R1", "U2", "R2", "U3")
    }

    with Session(engine) as session, session.begin():
        session.add(
            OrganizationRecord(
                id=organization_id,
                name=f"Unread pagination {organization_id}",
            )
        )
        session.flush()
        session.add_all(
            [
                UserRecord(
                    id=recipient_id,
                    organization_id=organization_id,
                    display_name="Unread Recipient",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=other_user_id,
                    organization_id=organization_id,
                    display_name="Unread Other User",
                    platform_role="ordinary_user",
                ),
            ]
        )
        session.flush()
        session.add(
            ScenarioRecord(
                id=scenario_id,
                organization_id=organization_id,
                key=f"unread_pagination_{uuid4().hex}",
                name="Unread Pagination Scenario",
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
                id=case_id,
                organization_id=organization_id,
                scenario_version_id=scenario_version_id,
                title="Unread pagination case",
                lifecycle="draft",
                scenario_data_json={},
                created_by=recipient_id,
                created_at=NOW,
            )
        )
        session.flush()

        service = build_notification_service(session)
        ordered_names = ("U3", "R2", "U2", "R1", "U1")
        for position, name in enumerate(ordered_names, start=1):
            occurred_at = NOW + timedelta(seconds=position)
            activity_id = activity_ids[name]
            session.add(
                ActivityRecord(
                    id=activity_id,
                    organization_id=organization_id,
                    actor_id=recipient_id,
                    event_type="review_case.member_added",
                    occurred_at=occurred_at,
                    review_case_id=case_id,
                    metadata_json={"label": name},
                )
            )
            session.flush()
            service.deliver(
                organization_id=organization_id,
                recipients=(recipient_id,),
                kind=NotificationKind.CASE_MEMBERSHIP_ADDED,
                origin_activity_id=activity_id,
                subject=ReviewCaseNotificationSubject(case_id),
                title=name,
                body=f"Notification {name}",
                created_at=occurred_at,
            )

        for read_name in ("R1", "R2"):
            notification_id = session.scalar(
                select(NotificationRecord.id).where(
                    NotificationRecord.organization_id == organization_id,
                    NotificationRecord.recipient_user_id == recipient_id,
                    NotificationRecord.origin_activity_id == activity_ids[read_name],
                )
            )
            assert notification_id is not None
            service.mark_read(organization_id, recipient_id, notification_id)

        other_activity_id = ActivityId(uuid4())
        session.add(
            ActivityRecord(
                id=other_activity_id,
                organization_id=organization_id,
                actor_id=other_user_id,
                event_type="review_case.member_added",
                occurred_at=NOW + timedelta(seconds=10),
                review_case_id=case_id,
                metadata_json={"label": "OTHER"},
            )
        )
        session.flush()
        service.deliver(
            organization_id=organization_id,
            recipients=(other_user_id,),
            kind=NotificationKind.CASE_MEMBERSHIP_ADDED,
            origin_activity_id=other_activity_id,
            subject=ReviewCaseNotificationSubject(case_id),
            title="OTHER",
            body="Must never leak into recipient inbox",
            created_at=NOW + timedelta(seconds=10),
        )

    return organization_id, recipient_id, activity_ids


def test_unread_filter_is_applied_before_deterministic_pagination(
    postgres_engine: Engine,
) -> None:
    organization_id, recipient_id, activity_ids = _seed_inbox(postgres_engine)

    with Session(postgres_engine) as session:
        service = build_notification_service(session)

        default_page = service.get_inbox(
            organization_id,
            recipient_id,
            limit=2,
            offset=0,
        )
        unread_page_1 = service.get_inbox(
            organization_id,
            recipient_id,
            limit=2,
            offset=0,
            unread_only=True,
        )
        unread_page_2 = service.get_inbox(
            organization_id,
            recipient_id,
            limit=2,
            offset=2,
            unread_only=True,
        )

        assert [item.title for item in default_page.items] == ["U1", "R1"]
        assert [item.title for item in unread_page_1.items] == ["U1", "U2"]
        assert [item.title for item in unread_page_2.items] == ["U3"]
        assert unread_page_1.unread_count == 3
        assert unread_page_2.unread_count == 3
        assert all(item.read_at is None for item in unread_page_1.items)
        assert all(item.read_at is None for item in unread_page_2.items)
        assert {item.origin_activity_id for item in unread_page_1.items + unread_page_2.items} == {
            activity_ids["U1"],
            activity_ids["U2"],
            activity_ids["U3"],
        }
