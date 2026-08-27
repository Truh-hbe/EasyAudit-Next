import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, select, update
from sqlalchemy.orm import Session

from easyaudit_next.collaboration.automatic_reminder import AutomaticReminderEvaluator
from easyaudit_next.collaboration.recipient_resolution import RecipientResolver
from easyaudit_next.composition import (
    build_automatic_reminder_evaluator,
    build_finding_lifecycle_service,
    build_rectification_service,
    build_review_planning_service,
)
from easyaudit_next.notifications.models import NotificationKind
from easyaudit_next.notifications.persistence import (
    NotificationRecord,
    SqlAlchemyNotificationRepository,
)
from easyaudit_next.notifications.service import NotificationService
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.domain.models import (
    AssignmentRole,
    FindingSeverity,
    Scenario,
    ScenarioKey,
    ScenarioVersion,
    UserActor,
)
from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActorKind,
    AuthorizationContext,
    CollaborationRecipientIntent,
    PermissionSource,
)
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry
from easyaudit_next.review_core.persistence.models import (
    ActionAssigneeRecord,
    ActionItemRecord,
    ActivityRecord,
    CaseMemberRecord,
    ReviewCaseRecord,
)
from easyaudit_next.scenarios.process_review import PROCESS_REVIEW_V1
from tests.integration.notification_test_support import NOW, seed_process_review_users


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


@dataclass(frozen=True, slots=True)
class ReminderFixture:
    organization_id: OrganizationId
    lead_id: UserId
    second_lead_id: UserId
    action_assignee_id: UserId
    action_collaborator_id: UserId
    review_case_id: UUID
    action_item_id: UUID


def _seed_reminder_fixture(engine: Engine) -> ReminderFixture:
    organization_id, _, ids = seed_process_review_users(engine)
    with Session(engine, expire_on_commit=False) as session:
        users = SqlAlchemyUserRepository(session)
        lead = users.get(ids["lead"])
        owner = users.get(ids["owner"])
        action_assignee = users.get(ids["action_assignee"])
        assert lead is not None
        assert owner is not None
        assert action_assignee is not None

        planning = build_review_planning_service(session)
        review_case = planning.create_case(
            lead,
            ScenarioKey("process_review"),
            ScenarioVersion(1),
            "M3.4 automatic reminder case",
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
            "Automatic reminder finding",
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
            "Automatic reminder action",
            occurred_at=NOW,
        )
        rectification.add_assignee_result(
            owner,
            action.id,
            UserActor(action_assignee.id),
            AssignmentRole.PRIMARY,
            occurred_at=NOW,
        )

        session.add(
            CaseMemberRecord(
                organization_id=organization_id,
                case_id=review_case.id,
                user_id=ids["observer_a"],
                role_key="lead",
                joined_at=NOW,
            )
        )
        session.add(
            ActionAssigneeRecord(
                id=uuid4(),
                organization_id=organization_id,
                action_item_id=action.id,
                user_id=ids["observer_b"],
                department_id=None,
                role="collaborator",
                assigned_at=NOW,
            )
        )
        session.execute(
            update(ReviewCaseRecord)
            .where(ReviewCaseRecord.id == review_case.id)
            .values(planned_end_at=NOW - timedelta(days=1))
        )
        session.execute(
            update(ActionItemRecord)
            .where(ActionItemRecord.id == action.id)
            .values(due_at=NOW - timedelta(hours=6))
        )
        session.commit()

        return ReminderFixture(
            organization_id=organization_id,
            lead_id=lead.id,
            second_lead_id=ids["observer_a"],
            action_assignee_id=action_assignee.id,
            action_collaborator_id=ids["observer_b"],
            review_case_id=review_case.id,
            action_item_id=action.id,
        )


def _automatic_notifications(
    session: Session,
    fixture: ReminderFixture,
    kind: NotificationKind,
) -> tuple[NotificationRecord, ...]:
    return tuple(
        session.scalars(
            select(NotificationRecord).where(
                NotificationRecord.organization_id == fixture.organization_id,
                NotificationRecord.kind == kind.value,
            )
        )
    )


def test_case_overdue_reminder_uses_scenario_recipients_and_appends_no_activity(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    with Session(postgres_engine) as session:
        before_activity_count = session.scalar(select(func.count()).select_from(ActivityRecord))
        result = build_automatic_reminder_evaluator(session).evaluate_case_overdue(
            fixture.organization_id,
            fixture.review_case_id,
            occurrence_key="overdue-run-2026-08-27",
            as_of=NOW,
        )
        session.commit()

    with Session(postgres_engine) as session:
        after_activity_count = session.scalar(select(func.count()).select_from(ActivityRecord))
        notifications = _automatic_notifications(
            session,
            fixture,
            NotificationKind.AUTOMATIC_CASE_REMINDER,
        )
        assert before_activity_count == after_activity_count
        assert result.eligible is True
        assert result.recipient_count == 2
        assert result.automatic_origin_key is not None
        assert {row.recipient_user_id for row in notifications} == {
            fixture.lead_id,
            fixture.second_lead_id,
        }
        assert {row.review_case_id for row in notifications} == {fixture.review_case_id}
        assert {row.origin_activity_id for row in notifications} == {None}
        assert {row.automatic_origin_key for row in notifications} == {
            result.automatic_origin_key
        }


def test_action_overdue_reminder_is_target_specific_and_appends_no_activity(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    with Session(postgres_engine) as session:
        before_activity_count = session.scalar(select(func.count()).select_from(ActivityRecord))
        result = build_automatic_reminder_evaluator(session).evaluate_action_overdue(
            fixture.organization_id,
            fixture.action_item_id,
            occurrence_key="overdue-run-2026-08-27",
            as_of=NOW,
        )
        session.commit()

    with Session(postgres_engine) as session:
        after_activity_count = session.scalar(select(func.count()).select_from(ActivityRecord))
        notifications = _automatic_notifications(
            session,
            fixture,
            NotificationKind.AUTOMATIC_ACTION_REMINDER,
        )
        assert before_activity_count == after_activity_count
        assert result.eligible is True
        assert result.recipient_count == 2
        assert {row.recipient_user_id for row in notifications} == {
            fixture.action_assignee_id,
            fixture.action_collaborator_id,
        }
        assert {row.action_item_id for row in notifications} == {fixture.action_item_id}
        assert {row.origin_activity_id for row in notifications} == {None}


def test_same_case_occurrence_is_database_idempotent_under_concurrency(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    barrier = Barrier(2)

    def evaluate_once() -> None:
        with Session(postgres_engine) as session:
            barrier.wait()
            build_automatic_reminder_evaluator(session).evaluate_case_overdue(
                fixture.organization_id,
                fixture.review_case_id,
                occurrence_key="concurrent-overdue-occurrence",
                as_of=NOW,
            )
            session.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(evaluate_once) for _ in range(2)]
        for future in futures:
            future.result(timeout=10)

    with Session(postgres_engine) as session:
        rows = tuple(
            session.scalars(
                select(NotificationRecord).where(
                    NotificationRecord.organization_id == fixture.organization_id,
                    NotificationRecord.review_case_id == fixture.review_case_id,
                    NotificationRecord.kind == NotificationKind.AUTOMATIC_CASE_REMINDER.value,
                )
            )
        )
        assert len(rows) == 2
        assert {row.recipient_user_id for row in rows} == {
            fixture.lead_id,
            fixture.second_lead_id,
        }
        assert len({row.automatic_origin_key for row in rows}) == 1


def test_changed_deadline_produces_new_identity_for_same_supplied_occurrence(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    with Session(postgres_engine) as session:
        first = build_automatic_reminder_evaluator(session).evaluate_case_overdue(
            fixture.organization_id,
            fixture.review_case_id,
            occurrence_key="same-policy-occurrence",
            as_of=NOW,
        )
        session.commit()

    with Session(postgres_engine) as session, session.begin():
        session.execute(
            update(ReviewCaseRecord)
            .where(ReviewCaseRecord.id == fixture.review_case_id)
            .values(planned_end_at=NOW - timedelta(hours=2))
        )

    with Session(postgres_engine) as session:
        second = build_automatic_reminder_evaluator(session).evaluate_case_overdue(
            fixture.organization_id,
            fixture.review_case_id,
            occurrence_key="same-policy-occurrence",
            as_of=NOW,
        )
        session.commit()

    assert first.automatic_origin_key is not None
    assert second.automatic_origin_key is not None
    assert first.automatic_origin_key != second.automatic_origin_key
    with Session(postgres_engine) as session:
        rows = tuple(
            session.scalars(
                select(NotificationRecord).where(
                    NotificationRecord.organization_id == fixture.organization_id,
                    NotificationRecord.review_case_id == fixture.review_case_id,
                    NotificationRecord.kind == NotificationKind.AUTOMATIC_CASE_REMINDER.value,
                )
            )
        )
        assert len(rows) == 4
        assert len({row.automatic_origin_key for row in rows}) == 2


def test_case_terminalized_during_recipient_resolution_is_revalidated_before_delivery(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    with Session(postgres_engine) as session:
        evaluator = build_automatic_reminder_evaluator(session)
        original_load = evaluator._recipients.load

        def load_then_terminalize(
            organization_id: OrganizationId,
            case_id: UUID,
        ):
            snapshot = original_load(organization_id, case_id)
            with Session(postgres_engine) as concurrent, concurrent.begin():
                concurrent.execute(
                    update(ReviewCaseRecord)
                    .where(ReviewCaseRecord.id == case_id)
                    .values(lifecycle="closed")
                )
            return snapshot

        monkeypatch.setattr(evaluator._recipients, "load", load_then_terminalize)
        result = evaluator.evaluate_case_overdue(
            fixture.organization_id,
            fixture.review_case_id,
            occurrence_key="stale-case-occurrence",
            as_of=NOW,
        )
        session.commit()

    assert result.eligible is False
    with Session(postgres_engine) as session:
        count = session.scalar(
            select(func.count())
            .select_from(NotificationRecord)
            .where(
                NotificationRecord.organization_id == fixture.organization_id,
                NotificationRecord.review_case_id == fixture.review_case_id,
                NotificationRecord.kind == NotificationKind.AUTOMATIC_CASE_REMINDER.value,
            )
        )
        assert count == 0


def test_action_terminalized_during_recipient_resolution_is_revalidated_before_delivery(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    with Session(postgres_engine) as session:
        evaluator = build_automatic_reminder_evaluator(session)
        original_load = evaluator._recipients.load

        def load_then_terminalize(
            organization_id: OrganizationId,
            case_id: UUID,
        ):
            snapshot = original_load(organization_id, case_id)
            with Session(postgres_engine) as concurrent, concurrent.begin():
                concurrent.execute(
                    update(ActionItemRecord)
                    .where(ActionItemRecord.id == fixture.action_item_id)
                    .values(lifecycle="done")
                )
            return snapshot

        monkeypatch.setattr(evaluator._recipients, "load", load_then_terminalize)
        result = evaluator.evaluate_action_overdue(
            fixture.organization_id,
            fixture.action_item_id,
            occurrence_key="stale-action-occurrence",
            as_of=NOW,
        )
        session.commit()

    assert result.eligible is False
    with Session(postgres_engine) as session:
        count = session.scalar(
            select(func.count())
            .select_from(NotificationRecord)
            .where(
                NotificationRecord.organization_id == fixture.organization_id,
                NotificationRecord.action_item_id == fixture.action_item_id,
                NotificationRecord.kind == NotificationKind.AUTOMATIC_ACTION_REMINDER.value,
            )
        )
        assert count == 0


def test_null_deadlines_are_not_automatic_reminder_candidates(
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
            .values(due_at=None)
        )

    with Session(postgres_engine) as session:
        evaluator = build_automatic_reminder_evaluator(session)
        case_result = evaluator.evaluate_case_overdue(
            fixture.organization_id,
            fixture.review_case_id,
            occurrence_key="null-deadline-case",
            as_of=NOW,
        )
        action_result = evaluator.evaluate_action_overdue(
            fixture.organization_id,
            fixture.action_item_id,
            occurrence_key="null-deadline-action",
            as_of=NOW,
        )
        session.commit()

    assert case_result.eligible is False
    assert action_result.eligible is False


class DivergentAuthorization:
    def allows(self, permission: str, context: AuthorizationContext) -> bool:
        if permission != "transition_case":
            return False
        return any(
            grant.role_key in {"deadline_owner", "emergency_auditor"}
            and grant.actor_kind is ActorKind.USER
            and grant.source is PermissionSource.DIRECT
            for grant in context.case_role_grants
        )


class DivergentRecipients:
    def is_recipient(
        self,
        intent: CollaborationRecipientIntent,
        context: AuthorizationContext,
    ) -> bool:
        if intent is not CollaborationRecipientIntent.CASE_DEADLINE:
            return False
        return any(
            grant.role_key == "deadline_owner"
            and grant.actor_kind is ActorKind.USER
            and grant.source is PermissionSource.DIRECT
            for grant in context.case_role_grants
        )


class NoRecipients:
    def is_recipient(
        self,
        intent: CollaborationRecipientIntent,
        context: AuthorizationContext,
    ) -> bool:
        return False


def test_exact_historical_scenario_recipient_semantics_can_diverge_from_authorization(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_reminder_fixture(postgres_engine)
    deadline_owner = UserId(uuid4())
    emergency_auditor = UserId(uuid4())

    with Session(postgres_engine) as session, session.begin():
        from easyaudit_next.platform.persistence.models import UserRecord

        session.add_all(
            [
                UserRecord(
                    id=deadline_owner,
                    organization_id=fixture.organization_id,
                    display_name="Deadline Owner",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=emergency_auditor,
                    organization_id=fixture.organization_id,
                    display_name="Emergency Auditor",
                    platform_role="ordinary_user",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                CaseMemberRecord(
                    organization_id=fixture.organization_id,
                    case_id=fixture.review_case_id,
                    user_id=deadline_owner,
                    role_key="deadline_owner",
                    joined_at=NOW,
                ),
                CaseMemberRecord(
                    organization_id=fixture.organization_id,
                    case_id=fixture.review_case_id,
                    user_id=emergency_auditor,
                    role_key="emergency_auditor",
                    joined_at=NOW,
                ),
            ]
        )

    v1 = replace(
        PROCESS_REVIEW_V1,
        authorization=DivergentAuthorization(),
        collaboration_recipients=DivergentRecipients(),
    )
    v2 = replace(
        PROCESS_REVIEW_V1,
        scenario=Scenario(
            key=ScenarioKey("process_review"),
            version=ScenarioVersion(2),
            name="Process Review v2 test-only",
        ),
        collaboration_recipients=NoRecipients(),
    )
    registry = ScenarioRegistry()
    registry.register(v1)
    registry.register(v2)

    with Session(postgres_engine) as session:
        resolver = RecipientResolver(session, registry)
        snapshot = resolver.load(fixture.organization_id, fixture.review_case_id)
        assert snapshot.policy.authorization.allows(
            "transition_case",
            snapshot.case_context(deadline_owner),
        )
        assert snapshot.policy.authorization.allows(
            "transition_case",
            snapshot.case_context(emergency_auditor),
        )

        evaluator = AutomaticReminderEvaluator(
            session,
            registry,
            NotificationService(SqlAlchemyNotificationRepository(session)),
        )
        result = evaluator.evaluate_case_overdue(
            fixture.organization_id,
            fixture.review_case_id,
            occurrence_key="divergent-recipient-occurrence",
            as_of=NOW,
        )
        session.commit()

    assert result.eligible is True
    assert result.recipient_count == 1
    with Session(postgres_engine) as session:
        recipients = set(
            session.scalars(
                select(NotificationRecord.recipient_user_id).where(
                    NotificationRecord.organization_id == fixture.organization_id,
                    NotificationRecord.review_case_id == fixture.review_case_id,
                    NotificationRecord.kind
                    == NotificationKind.AUTOMATIC_CASE_REMINDER.value,
                )
            )
        )
        assert recipients == {deadline_owner}
