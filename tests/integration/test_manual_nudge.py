import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session

from easyaudit_next.collaboration.nudge import (
    ManualNudgeService,
    NudgeValidationError,
)
from easyaudit_next.composition import (
    build_finding_lifecycle_service,
    build_manual_nudge_service,
    build_rectification_service,
    build_review_planning_service,
    build_scenario_registry,
)
from easyaudit_next.notifications.models import NotificationKind
from easyaudit_next.notifications.persistence import NotificationRecord
from easyaudit_next.notifications.service import NotificationService
from easyaudit_next.platform.domain.ids import UserId
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.domain.models import (
    AssignmentRole,
    DepartmentActor,
    FindingSeverity,
    ScenarioKey,
    ScenarioVersion,
    UserActor,
)
from easyaudit_next.review_core.persistence.models import (
    ActionItemRecord,
    ActivityRecord,
    FindingRecord,
)
from tests.integration.notification_test_support import NOW, seed_process_review_users


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


@dataclass(frozen=True, slots=True)
class NudgeFixture:
    organization_id: object
    lead_id: UserId
    owner_id: UserId
    assignee_id: UserId
    finding_id: UUID
    action_item_id: UUID


def _seed_nudge_fixture(
    engine: Engine,
    *,
    owner_is_lead: bool = False,
) -> NudgeFixture:
    organization_id, department_id, ids = seed_process_review_users(engine)
    with Session(engine, expire_on_commit=False) as session:
        users = SqlAlchemyUserRepository(session)
        lead = users.get(ids["lead"])
        owner = lead if owner_is_lead else users.get(ids["owner"])
        assignee = users.get(ids["action_assignee"])
        assert lead is not None
        assert owner is not None
        assert assignee is not None

        planning = build_review_planning_service(session)
        review_case = planning.create_case(
            lead,
            ScenarioKey("process_review"),
            ScenarioVersion(1),
            "M3.4 manual nudge case",
            {"area_code": "ASSY", "review_type": "routine"},
            occurred_at=NOW,
        )
        review_case = planning.transition_case(
            lead,
            review_case.id,
            "schedule",
            occurred_at=NOW,
        )
        review_case = planning.transition_case(
            lead,
            review_case.id,
            "start",
            occurred_at=NOW,
        )

        findings = build_finding_lifecycle_service(session)
        finding = findings.create_finding(
            lead,
            review_case.id,
            "Manual nudge finding",
            FindingSeverity.HIGH,
            {"issue_type": "control_gap", "project_category": "assembly"},
            occurred_at=NOW,
        )
        findings.add_participant_result(
            lead,
            finding.id,
            UserActor(owner.id),
            "owner",
            occurred_at=NOW,
        )
        findings.add_participant_result(
            lead,
            finding.id,
            DepartmentActor(department_id),
            "responsible_department",
            occurred_at=NOW,
        )
        finding = findings.transition_finding(
            lead,
            finding.id,
            "issue",
            occurred_at=NOW,
        )

        rectification = build_rectification_service(session)
        action = rectification.create_action_item(
            owner,
            finding.id,
            "Manual nudge action",
            occurred_at=NOW,
        )
        rectification.add_assignee_result(
            owner,
            action.id,
            UserActor(assignee.id),
            AssignmentRole.PRIMARY,
            occurred_at=NOW,
        )
        session.commit()
        return NudgeFixture(
            organization_id=organization_id,
            lead_id=lead.id,
            owner_id=owner.id,
            assignee_id=assignee.id,
            finding_id=finding.id,
            action_item_id=action.id,
        )


def test_manual_finding_nudge_has_exact_activity_provenance_and_no_lifecycle_change(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_nudge_fixture(postgres_engine)
    with Session(postgres_engine, expire_on_commit=False) as session:
        lead = SqlAlchemyUserRepository(session).get(fixture.lead_id)
        assert lead is not None
        before_lifecycle = session.scalar(
            select(FindingRecord.lifecycle).where(FindingRecord.id == fixture.finding_id)
        )
        result = build_manual_nudge_service(session).nudge_finding(
            lead,
            fixture.finding_id,
            occurred_at=NOW,
        )
        session.commit()

    with Session(postgres_engine) as session:
        activity = session.get(ActivityRecord, result.activity_id)
        assert activity is not None
        assert activity.finding_id == fixture.finding_id
        assert activity.action_item_id is None
        assert activity.actor_id == fixture.lead_id
        assert activity.event_type == "finding.nudged"

        notifications = tuple(
            session.scalars(
                select(NotificationRecord).where(
                    NotificationRecord.organization_id == fixture.organization_id,
                    NotificationRecord.origin_activity_id == result.activity_id,
                    NotificationRecord.kind == NotificationKind.MANUAL_FINDING_NUDGE.value,
                )
            )
        )
        assert len(notifications) == 1
        assert notifications[0].recipient_user_id == fixture.owner_id
        assert notifications[0].finding_id == fixture.finding_id
        assert result.recipient_count == 1
        assert session.scalar(
            select(FindingRecord.lifecycle).where(FindingRecord.id == fixture.finding_id)
        ) == before_lifecycle


def test_manual_action_nudge_uses_action_responsibility_and_exact_subject(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_nudge_fixture(postgres_engine)
    with Session(postgres_engine, expire_on_commit=False) as session:
        lead = SqlAlchemyUserRepository(session).get(fixture.lead_id)
        assert lead is not None
        before_lifecycle = session.scalar(
            select(ActionItemRecord.lifecycle).where(
                ActionItemRecord.id == fixture.action_item_id
            )
        )
        result = build_manual_nudge_service(session).nudge_action_item(
            lead,
            fixture.action_item_id,
            occurred_at=NOW,
        )
        session.commit()

    with Session(postgres_engine) as session:
        activity = session.get(ActivityRecord, result.activity_id)
        assert activity is not None
        assert activity.action_item_id == fixture.action_item_id
        assert activity.finding_id is None
        assert activity.actor_id == fixture.lead_id
        assert activity.event_type == "action_item.nudged"

        notifications = tuple(
            session.scalars(
                select(NotificationRecord).where(
                    NotificationRecord.organization_id == fixture.organization_id,
                    NotificationRecord.origin_activity_id == result.activity_id,
                    NotificationRecord.kind == NotificationKind.MANUAL_ACTION_NUDGE.value,
                )
            )
        )
        assert len(notifications) == 1
        assert notifications[0].recipient_user_id == fixture.assignee_id
        assert notifications[0].action_item_id == fixture.action_item_id
        assert result.recipient_count == 1
        assert session.scalar(
            select(ActionItemRecord.lifecycle).where(
                ActionItemRecord.id == fixture.action_item_id
            )
        ) == before_lifecycle


def test_zero_recipient_fails_before_activity_or_notification(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_nudge_fixture(postgres_engine, owner_is_lead=True)
    with Session(postgres_engine) as session:
        lead = SqlAlchemyUserRepository(session).get(fixture.lead_id)
        assert lead is not None
        before_activities = session.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(
                ActivityRecord.organization_id == fixture.organization_id,
                ActivityRecord.finding_id == fixture.finding_id,
                ActivityRecord.event_type == "finding.nudged",
            )
        )
        before_notifications = session.scalar(
            select(func.count())
            .select_from(NotificationRecord)
            .where(
                NotificationRecord.organization_id == fixture.organization_id,
                NotificationRecord.finding_id == fixture.finding_id,
                NotificationRecord.kind == NotificationKind.MANUAL_FINDING_NUDGE.value,
            )
        )

        with pytest.raises(NudgeValidationError, match="No eligible nudge recipients"):
            build_manual_nudge_service(session).nudge_finding(
                lead,
                fixture.finding_id,
                occurred_at=NOW,
            )

        assert session.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(
                ActivityRecord.organization_id == fixture.organization_id,
                ActivityRecord.finding_id == fixture.finding_id,
                ActivityRecord.event_type == "finding.nudged",
            )
        ) == before_activities
        assert session.scalar(
            select(func.count())
            .select_from(NotificationRecord)
            .where(
                NotificationRecord.organization_id == fixture.organization_id,
                NotificationRecord.finding_id == fixture.finding_id,
                NotificationRecord.kind == NotificationKind.MANUAL_FINDING_NUDGE.value,
            )
        ) == before_notifications


class _FailingNotifications:
    def deliver(self, **_: object) -> None:
        raise RuntimeError("forced notification persistence failure")


def test_notification_failure_rolls_back_manual_nudge_activity(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_nudge_fixture(postgres_engine)
    with Session(postgres_engine) as session:
        lead = SqlAlchemyUserRepository(session).get(fixture.lead_id)
        assert lead is not None
        service = ManualNudgeService(
            session,
            build_scenario_registry(),
            cast(NotificationService, _FailingNotifications()),
        )
        with pytest.raises(RuntimeError, match="forced notification persistence failure"):
            service.nudge_finding(lead, fixture.finding_id, occurred_at=NOW)
        session.rollback()

    with Session(postgres_engine) as session:
        assert session.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(
                ActivityRecord.organization_id == fixture.organization_id,
                ActivityRecord.finding_id == fixture.finding_id,
                ActivityRecord.event_type == "finding.nudged",
            )
        ) == 0
