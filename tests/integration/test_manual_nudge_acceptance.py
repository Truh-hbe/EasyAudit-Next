import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, select, update
from sqlalchemy.orm import Session

from easyaudit_next.collaboration.nudge import ManualNudgeService
from easyaudit_next.notifications.models import NotificationKind
from easyaudit_next.notifications.persistence import (
    NotificationRecord,
    SqlAlchemyNotificationRepository,
)
from easyaudit_next.notifications.service import NotificationService
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.persistence.models import UserRecord
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActorKind,
    AuthorizationContext,
    PermissionSource,
)
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry
from easyaudit_next.review_core.persistence.models import (
    ActionAssigneeRecord,
    ActivityRecord,
    CaseMemberRecord,
    FindingRecord,
)
from easyaudit_next.scenarios.process_review import PROCESS_REVIEW_V1
from tests.integration.notification_test_support import NOW
from tests.integration.test_manual_nudge import _seed_nudge_fixture


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _organization_id(value: object) -> OrganizationId:
    return cast(OrganizationId, value)


def _case_id(session: Session, finding_id: UUID) -> UUID:
    case_id = session.scalar(
        select(FindingRecord.case_id).where(FindingRecord.id == finding_id)
    )
    assert case_id is not None
    return case_id


def _unused_user_id(
    session: Session,
    organization_id: OrganizationId,
    excluded: set[UUID],
) -> UserId:
    value = session.scalar(
        select(UserRecord.id)
        .where(
            UserRecord.organization_id == organization_id,
            UserRecord.id.not_in(excluded),
            UserRecord.is_active.is_(True),
        )
        .order_by(UserRecord.id)
        .limit(1)
    )
    assert value is not None
    return UserId(value)


def test_near_concurrent_manual_nudges_keep_each_notification_set_on_its_exact_activity(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_nudge_fixture(postgres_engine)
    barrier = Barrier(2)

    def nudge_once() -> UUID:
        with Session(postgres_engine) as session:
            lead = SqlAlchemyUserRepository(session).get(fixture.lead_id)
            assert lead is not None
            barrier.wait()
            result = ManualNudgeService(
                session,
                ScenarioRegistryWithProcessReview(),
                NotificationService(SqlAlchemyNotificationRepository(session)),
            ).nudge_finding(lead, fixture.finding_id, occurred_at=NOW)
            session.commit()
            return UUID(str(result.activity_id))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(nudge_once) for _ in range(2)]
        activity_ids = {future.result(timeout=10) for future in futures}

    assert len(activity_ids) == 2
    with Session(postgres_engine) as session:
        activities = tuple(
            session.scalars(
                select(ActivityRecord).where(
                    ActivityRecord.id.in_(activity_ids),
                    ActivityRecord.finding_id == fixture.finding_id,
                    ActivityRecord.event_type == "finding.nudged",
                )
            )
        )
        notifications = tuple(
            session.scalars(
                select(NotificationRecord).where(
                    NotificationRecord.organization_id == fixture.organization_id,
                    NotificationRecord.origin_activity_id.in_(activity_ids),
                    NotificationRecord.kind == NotificationKind.MANUAL_FINDING_NUDGE.value,
                )
            )
        )
        assert {row.id for row in activities} == activity_ids
        assert len(notifications) == 2
        assert {row.origin_activity_id for row in notifications} == activity_ids
        assert {row.recipient_user_id for row in notifications} == {fixture.owner_id}
        for activity_id in activity_ids:
            assert sum(row.origin_activity_id == activity_id for row in notifications) == 1


def test_duplicate_legal_action_responsibility_paths_still_emit_one_notification(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_nudge_fixture(postgres_engine)
    organization_id = _organization_id(fixture.organization_id)
    with Session(postgres_engine) as session, session.begin():
        session.add(
            ActionAssigneeRecord(
                id=uuid4(),
                organization_id=organization_id,
                action_item_id=fixture.action_item_id,
                user_id=fixture.assignee_id,
                department_id=None,
                role="collaborator",
                assigned_at=NOW,
            )
        )

    with Session(postgres_engine) as session:
        lead = SqlAlchemyUserRepository(session).get(fixture.lead_id)
        assert lead is not None
        result = ManualNudgeService(
            session,
            ScenarioRegistryWithProcessReview(),
            NotificationService(SqlAlchemyNotificationRepository(session)),
        ).nudge_action_item(lead, fixture.action_item_id, occurred_at=NOW)
        session.commit()

    assert result.recipient_count == 1
    with Session(postgres_engine) as session:
        rows = tuple(
            session.scalars(
                select(NotificationRecord).where(
                    NotificationRecord.organization_id == organization_id,
                    NotificationRecord.origin_activity_id == result.activity_id,
                    NotificationRecord.kind == NotificationKind.MANUAL_ACTION_NUDGE.value,
                )
            )
        )
        assert len(rows) == 1
        assert rows[0].recipient_user_id == fixture.assignee_id


def test_observer_case_member_cannot_nudge_even_though_the_target_is_visible(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_nudge_fixture(postgres_engine)
    organization_id = _organization_id(fixture.organization_id)
    with Session(postgres_engine) as session, session.begin():
        observer_id = _unused_user_id(
            session,
            organization_id,
            {fixture.lead_id, fixture.owner_id, fixture.assignee_id},
        )
        session.add(
            CaseMemberRecord(
                organization_id=organization_id,
                case_id=_case_id(session, fixture.finding_id),
                user_id=observer_id,
                role_key="observer",
                joined_at=NOW,
            )
        )

    with Session(postgres_engine) as session:
        observer = SqlAlchemyUserRepository(session).get(observer_id)
        assert observer is not None
        with pytest.raises(LookupError):
            ManualNudgeService(
                session,
                ScenarioRegistryWithProcessReview(),
                NotificationService(SqlAlchemyNotificationRepository(session)),
            ).nudge_finding(observer, fixture.finding_id, occurred_at=NOW)
        session.rollback()

    with Session(postgres_engine) as session:
        assert session.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(
                ActivityRecord.organization_id == organization_id,
                ActivityRecord.finding_id == fixture.finding_id,
                ActivityRecord.event_type == "finding.nudged",
            )
        ) == 0


def test_system_admin_without_scenario_business_authority_has_no_nudge_bypass(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_nudge_fixture(postgres_engine)
    organization_id = _organization_id(fixture.organization_id)
    with Session(postgres_engine) as session, session.begin():
        system_admin_id = _unused_user_id(
            session,
            organization_id,
            {fixture.lead_id, fixture.owner_id, fixture.assignee_id},
        )
        session.execute(
            update(UserRecord)
            .where(UserRecord.id == system_admin_id)
            .values(platform_role="system_admin")
        )

    with Session(postgres_engine) as session:
        system_admin = SqlAlchemyUserRepository(session).get(system_admin_id)
        assert system_admin is not None
        with pytest.raises(LookupError):
            ManualNudgeService(
                session,
                ScenarioRegistryWithProcessReview(),
                NotificationService(SqlAlchemyNotificationRepository(session)),
            ).nudge_finding(system_admin, fixture.finding_id, occurred_at=NOW)
        session.rollback()


def test_cross_organization_target_is_non_disclosing_and_creates_no_nudge_activity(
    postgres_engine: Engine,
) -> None:
    actor_fixture = _seed_nudge_fixture(postgres_engine)
    foreign_fixture = _seed_nudge_fixture(postgres_engine)
    actor_org = _organization_id(actor_fixture.organization_id)

    with Session(postgres_engine) as session:
        lead = SqlAlchemyUserRepository(session).get(actor_fixture.lead_id)
        assert lead is not None
        with pytest.raises(LookupError, match="Finding not found"):
            ManualNudgeService(
                session,
                ScenarioRegistryWithProcessReview(),
                NotificationService(SqlAlchemyNotificationRepository(session)),
            ).nudge_finding(lead, foreign_fixture.finding_id, occurred_at=NOW)
        session.rollback()

    with Session(postgres_engine) as session:
        assert session.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(
                ActivityRecord.organization_id == actor_org,
                ActivityRecord.event_type == "finding.nudged",
            )
        ) == 0


class NudgeManagerAuthorization:
    def allows(self, permission: str, context: AuthorizationContext) -> bool:
        direct_case_roles = {
            grant.role_key
            for grant in context.case_role_grants
            if grant.actor_kind is ActorKind.USER
            and grant.source is PermissionSource.DIRECT
        }
        if permission in {"manage_case_members", "view_case", "view_finding"}:
            return "nudge_manager" in direct_case_roles
        return False


class ScenarioRegistryWithProcessReview(ScenarioRegistry):
    def __init__(self) -> None:
        super().__init__()
        self.register(PROCESS_REVIEW_V1)


def test_manual_sender_authorization_consumes_scenario_policy_not_lead_role_name(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_nudge_fixture(postgres_engine)
    organization_id = _organization_id(fixture.organization_id)
    with Session(postgres_engine) as session, session.begin():
        manager_id = _unused_user_id(
            session,
            organization_id,
            {fixture.lead_id, fixture.owner_id, fixture.assignee_id},
        )
        session.add(
            CaseMemberRecord(
                organization_id=organization_id,
                case_id=_case_id(session, fixture.finding_id),
                user_id=manager_id,
                role_key="nudge_manager",
                joined_at=NOW,
            )
        )

    custom_registry = ScenarioRegistry()
    custom_registry.register(
        replace(PROCESS_REVIEW_V1, authorization=NudgeManagerAuthorization())
    )
    with Session(postgres_engine) as session:
        manager = SqlAlchemyUserRepository(session).get(manager_id)
        assert manager is not None
        result = ManualNudgeService(
            session,
            custom_registry,
            NotificationService(SqlAlchemyNotificationRepository(session)),
        ).nudge_finding(manager, fixture.finding_id, occurred_at=NOW)
        session.commit()

    assert result.recipient_count == 1
    with Session(postgres_engine) as session:
        row = session.scalar(
            select(NotificationRecord).where(
                NotificationRecord.organization_id == organization_id,
                NotificationRecord.origin_activity_id == result.activity_id,
                NotificationRecord.kind == NotificationKind.MANUAL_FINDING_NUDGE.value,
            )
        )
        assert row is not None
        assert row.recipient_user_id == fixture.owner_id
