"""B5 (#86): atomic "transfer and reopen" of a DONE ActionItem, on real PostgreSQL.

Journey: primary completes -> Finding submitted -> primary deactivated -> reviewer rejects ->
Finding owner transfers and reopens -> new executor completes. Then the guards, and
double-Session races (Case lock, new-executor deactivation, lock order).
"""

import os
import re
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, event, func, select, text
from sqlalchemy.orm import Session

from easyaudit_next.composition import (
    build_case_team_coordinator,
    build_rectification_service,
    build_verification_closure_service,
)
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.domain.models import User
from easyaudit_next.platform.persistence.models import OrganizationRecord, UserRecord
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.application.authorization import (
    ConcurrentCaseTransitionError,
    ReviewAuthorizationError,
)
from easyaudit_next.review_core.application.review_findings import (
    ConcurrentFindingTransitionError,
)
from easyaudit_next.review_core.application.review_rectification import (
    ConcurrentActionItemTransitionError,
)
from easyaudit_next.review_core.domain.ids import ActionItemId, FindingId
from easyaudit_next.review_core.domain.scenario_capabilities import ActionItemOperationError
from easyaudit_next.review_core.persistence.models import (
    ActionAssigneeRecord,
    ActionItemRecord,
    ActivityRecord,
    CaseMemberRecord,
    FindingParticipantRecord,
    FindingRecord,
    ReviewCaseRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
EVENT = "action_item.transferred_and_reopened"
WAITER = "b5_transfer_waiter"

SCENARIOS = {
    "process_review": (
        {"area_code": "ASSY", "review_type": "routine"},
        {"issue_type": "control_gap", "project_category": "assembly"},
    ),
    "compliance_review": (
        {"standard_reference": "ISO 9001:2015", "scope_summary": "Shared proof"},
        {"criterion_reference": "8.5.1", "finding_type": "nonconformity"},
    ),
}


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


class Seed:
    """One Case with a rectifying Finding and one ActionItem in the requested lifecycle."""

    def __init__(
        self,
        engine: Engine,
        *,
        scenario_key: str = "process_review",
        action_lifecycle: str = "done",
        finding_lifecycle: str = "rectifying",
        case_lifecycle: str = "in_progress",
        with_collaborator: bool = False,
        executors_active: bool = False,
    ) -> None:
        """By default every executor is deactivated: the only situation transfer is for."""
        self.engine = engine
        self.organization_id = OrganizationId(uuid4())
        self.owner, self.primary, self.collaborator, self.new1, self.new2 = (
            UserId(uuid4()) for _ in range(5)
        )
        self.lead, self.reviewer, self.admin, self.bystander = (UserId(uuid4()) for _ in range(4))
        self.case_id, self.finding_id, self.action_id = uuid4(), uuid4(), uuid4()
        self.completed_at = NOW - timedelta(hours=3)
        case_data, finding_data = SCENARIOS[scenario_key]
        org = self.organization_id
        scenario_id, version_id = uuid4(), uuid4()
        with Session(engine) as session, session.begin():
            session.add(OrganizationRecord(id=org, name=f"B5 {org}"))
            session.flush()
            session.add_all(
                UserRecord(
                    id=user_id,
                    organization_id=org,
                    display_name=name,
                    platform_role="system_admin" if user_id == self.admin else "ordinary_user",
                    is_active=executors_active or user_id not in (self.primary, self.collaborator),
                )
                for user_id, name in (
                    (self.owner, "Owner"),
                    (self.primary, "Primary"),
                    (self.collaborator, "Collaborator"),
                    (self.new1, "New 1"),
                    (self.new2, "New 2"),
                    (self.lead, "Lead"),
                    (self.reviewer, "Reviewer"),
                    (self.admin, "Admin"),
                    (self.bystander, "Bystander"),
                )
            )
            session.flush()
            session.add(
                ScenarioRecord(id=scenario_id, organization_id=org, key=scenario_key, name="S")
            )
            session.flush()
            session.add(
                ScenarioVersionRecord(
                    id=version_id,
                    scenario_id=scenario_id,
                    organization_id=org,
                    version=1,
                    published_at=NOW,
                )
            )
            session.flush()
            session.add(
                ReviewCaseRecord(
                    id=self.case_id,
                    organization_id=org,
                    plan_id=None,
                    scenario_version_id=version_id,
                    title="B5 transfer",
                    lifecycle=case_lifecycle,
                    planned_start_at=None,
                    planned_end_at=None,
                    started_at=NOW,
                    fieldwork_completed_at=None,
                    closed_at=None,
                    scenario_data_json=case_data,
                    created_by=self.lead,
                    created_at=NOW,
                )
            )
            session.flush()
            session.add_all(
                CaseMemberRecord(
                    organization_id=org,
                    case_id=self.case_id,
                    user_id=user_id,
                    role_key=role,
                    joined_at=NOW,
                )
                for user_id, role in ((self.lead, "lead"), (self.reviewer, "reviewer"))
            )
            session.flush()
            session.add(
                FindingRecord(
                    id=self.finding_id,
                    organization_id=org,
                    case_id=self.case_id,
                    title="Seed finding",
                    description=None,
                    severity="high",
                    lifecycle=finding_lifecycle,
                    raised_by=self.lead,
                    raised_at=NOW,
                    scenario_data_json=finding_data,
                )
            )
            session.flush()
            session.add(
                FindingParticipantRecord(
                    id=uuid4(),
                    organization_id=org,
                    finding_id=self.finding_id,
                    user_id=self.owner,
                    department_id=None,
                    role_key="owner",
                    assigned_at=NOW,
                )
            )
            session.add(
                ActionItemRecord(
                    id=self.action_id,
                    organization_id=org,
                    finding_id=self.finding_id,
                    title="Fix it",
                    lifecycle=action_lifecycle,
                    due_at=None,
                    completed_at=self.completed_at if action_lifecycle == "done" else None,
                )
            )
            session.flush()
            session.add(self._assignee(self.primary, "primary"))
            if with_collaborator:
                session.add(self._assignee(self.collaborator, "collaborator"))

    def _assignee(self, user_id: UserId, role: str) -> ActionAssigneeRecord:
        return ActionAssigneeRecord(
            id=uuid4(),
            organization_id=self.organization_id,
            action_item_id=self.action_id,
            user_id=user_id,
            role=role,
            assigned_at=NOW - timedelta(days=1),
        )

    def user(self, session: Session, user_id: UserId) -> User:
        user = SqlAlchemyUserRepository(session).get(user_id)
        assert user is not None
        return user

    def set_active(self, user_id: UserId, active: bool) -> None:
        with Session(self.engine) as session, session.begin():
            record = session.get(UserRecord, user_id)
            assert record is not None
            record.is_active = active

    def transfer(
        self,
        session: Session,
        actor_id: UserId,
        new_executor: UserId,
        reason: str = "Original executor left the company",
    ) -> object:
        return build_rectification_service(session).transfer_and_reopen_action(
            self.user(session, actor_id),
            ActionItemId(self.action_id),
            new_executor,
            reason,
            occurred_at=NOW,
        )

    def transfer_committed(
        self, actor_id: UserId, new_executor: UserId, reason: str = "left the company"
    ) -> None:
        with Session(self.engine) as session, session.begin():
            self.transfer(session, actor_id, new_executor, reason)

    def action(self) -> ActionItemRecord:
        with Session(self.engine) as session:
            record = session.get(ActionItemRecord, self.action_id)
            assert record is not None
            session.expunge(record)
            return record

    def assignees(self) -> set[tuple[UUID, str]]:
        with Session(self.engine) as session:
            rows = session.execute(
                select(ActionAssigneeRecord.user_id, ActionAssigneeRecord.role).where(
                    ActionAssigneeRecord.action_item_id == self.action_id
                )
            )
            return {(row[0], row[1]) for row in rows}

    def count(self, model: Any, *criteria: Any) -> int:
        with Session(self.engine) as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.organization_id == self.organization_id, *criteria)
                )
                or 0
            )

    def transfer_activities(self) -> list[ActivityRecord]:
        with Session(self.engine) as session:
            records = list(
                session.scalars(
                    select(ActivityRecord).where(
                        ActivityRecord.organization_id == self.organization_id,
                        ActivityRecord.event_type == EVENT,
                    )
                )
            )
            session.expunge_all()
            return records

    def assert_untouched(self) -> None:
        action = self.action()
        assert action.lifecycle == "done"
        assert action.completed_at == self.completed_at
        assert self.transfer_activities() == []
        assert (self.new1, "primary") not in self.assignees()
        assert (self.new2, "primary") not in self.assignees()


@pytest.mark.parametrize("scenario_key", sorted(SCENARIOS))
def test_issue_86_b5_journey_owner_transfers_and_new_executor_finishes(
    postgres_engine: Engine, scenario_key: str
) -> None:
    seed = Seed(
        postgres_engine,
        scenario_key=scenario_key,
        action_lifecycle="todo",
        executors_active=True,
    )
    completion = {"stage": "completion", "comment": "all done"}

    with Session(postgres_engine) as session, session.begin():
        rectification = build_rectification_service(session)
        primary = seed.user(session, seed.primary)
        rectification.transition_action_item(
            primary, ActionItemId(seed.action_id), "start", occurred_at=NOW
        )
        rectification.transition_action_item(
            primary, ActionItemId(seed.action_id), "complete", occurred_at=NOW
        )
        rectification.submit_rectification(
            seed.user(session, seed.owner),
            FindingId(seed.finding_id),
            "submit_for_verification",
            completion,
            occurred_at=NOW,
        )
    completed_at = seed.action().completed_at
    assert completed_at is not None

    with Session(postgres_engine) as session, session.begin():
        build_case_team_coordinator(session).update_user(
            seed.user(session, seed.admin), seed.primary, is_active=False, now=NOW
        )
    with Session(postgres_engine) as session, session.begin():
        build_verification_closure_service(session).submit_verification(
            seed.user(session, seed.reviewer),
            FindingId(seed.finding_id),
            "reject",
            {"result": "rejected", "comment": "not good enough"},
            occurred_at=NOW,
        )

    # The documented dead end: nobody active can touch the original ActionItem.
    with Session(postgres_engine) as session, session.begin():
        owner = seed.user(session, seed.owner)
        service = build_rectification_service(session)
        with pytest.raises(ReviewAuthorizationError):
            service.transition_action_item(owner, ActionItemId(seed.action_id), "reopen")

    seed.transfer_committed(seed.owner, seed.new1, "Primary left the company")

    action = seed.action()
    assert action.lifecycle == "in_progress"
    assert action.completed_at is None
    # the deactivated primary is dropped from the list, the new executor is primary
    assert seed.assignees() == {(seed.new1, "primary")}
    (activity,) = seed.transfer_activities()
    assert activity.actor_id == seed.owner
    assert activity.action_item_id == seed.action_id
    metadata = activity.metadata_json
    assert metadata["reason"] == "Primary left the company"
    assert metadata["from_lifecycle"] == "done"
    assert metadata["to_lifecycle"] == "in_progress"
    assert metadata["previous_completed_at"] == completed_at.isoformat()
    assert metadata["new_assignee_actor_id"] == str(seed.new1)
    assert metadata["previous_assignees"] == [
        {"actor_kind": "user", "actor_id": str(seed.primary), "role": "primary"}
    ]
    assert metadata["removed_assignees"] == metadata["previous_assignees"]
    # the earlier completion facts are still in the append-only history
    assert seed.count(ActivityRecord, ActivityRecord.event_type == "action_item.transitioned") == 2
    with Session(postgres_engine) as session, session.begin():
        service = build_rectification_service(session)
        new_executor = seed.user(session, seed.new1)
        service.transition_action_item(
            new_executor, ActionItemId(seed.action_id), "complete", occurred_at=NOW
        )
        service.submit_rectification(
            seed.user(session, seed.owner),
            FindingId(seed.finding_id),
            "submit_for_verification",
            completion,
            occurred_at=NOW,
        )
    assert seed.action().lifecycle == "done"


def test_all_executors_deactivated_primary_and_collaborator_are_dropped(
    postgres_engine: Engine,
) -> None:
    seed = Seed(postgres_engine, with_collaborator=True)

    seed.transfer_committed(seed.owner, seed.new1)

    assert seed.assignees() == {(seed.new1, "primary")}
    (activity,) = seed.transfer_activities()
    removed = activity.metadata_json["removed_assignees"]
    assert {(item["actor_id"], item["role"]) for item in removed} == {
        (str(seed.primary), "primary"),
        (str(seed.collaborator), "collaborator"),
    }
    assert activity.metadata_json["previous_assignees"] == removed


def test_an_action_with_no_executor_at_all_can_be_transferred(postgres_engine: Engine) -> None:
    seed = Seed(postgres_engine)
    with Session(postgres_engine) as session, session.begin():
        session.execute(
            text("DELETE FROM action_assignees WHERE action_item_id = :id"),
            {"id": seed.action_id},
        )

    seed.transfer_committed(seed.owner, seed.new1)

    assert seed.assignees() == {(seed.new1, "primary")}


@pytest.mark.parametrize("active", ["primary", "collaborator"])
@pytest.mark.parametrize("target", ["new1", "same"])
def test_an_active_executor_blocks_the_command_with_a_422(
    postgres_engine: Engine, active: str, target: str
) -> None:
    """Scope: only for an action nobody active can act on. With an active executor the owner
    must not be able to reopen (or re-staff) the action, not even by naming that executor."""
    seed = Seed(postgres_engine, with_collaborator=True)
    seed.set_active(getattr(seed, active), True)
    new_executor = seed.new1 if target == "new1" else getattr(seed, active)

    with Session(postgres_engine) as session, session.begin():
        with pytest.raises(ActionItemOperationError, match="active executor"):
            seed.transfer(session, seed.owner, new_executor)

    assert seed.action().lifecycle == "done"
    assert seed.transfer_activities() == []
    assert seed.assignees() == {(seed.primary, "primary"), (seed.collaborator, "collaborator")}


@pytest.mark.parametrize("scenario_key", sorted(SCENARIOS))
@pytest.mark.parametrize(
    "actor_name", ["lead", "reviewer", "primary", "collaborator", "admin", "bystander", "new1"]
)
def test_only_the_finding_owner_may_transfer(
    postgres_engine: Engine, scenario_key: str, actor_name: str
) -> None:
    seed = Seed(postgres_engine, scenario_key=scenario_key, with_collaborator=True)

    with Session(postgres_engine) as session, session.begin():
        with pytest.raises(ReviewAuthorizationError):
            seed.transfer(session, getattr(seed, actor_name), seed.new2)

    seed.assert_untouched()


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"action_lifecycle": "in_progress"}, ActionItemOperationError),
        ({"action_lifecycle": "todo"}, ActionItemOperationError),
        ({"action_lifecycle": "cancelled"}, ActionItemOperationError),
        ({"finding_lifecycle": "verifying"}, ActionItemOperationError),
        ({"finding_lifecycle": "closed"}, ActionItemOperationError),
        ({"case_lifecycle": "closed"}, ActionItemOperationError),
    ],
)
def test_state_preconditions_are_enforced_with_no_side_effects(
    postgres_engine: Engine, kwargs: dict[str, str], error: type[Exception]
) -> None:
    seed = Seed(postgres_engine, **kwargs)
    before = seed.action()

    with Session(postgres_engine) as session, session.begin():
        with pytest.raises(error):
            seed.transfer(session, seed.owner, seed.new1)

    assert seed.action().lifecycle == before.lifecycle
    assert seed.transfer_activities() == []
    assert seed.assignees() == {(seed.primary, "primary")}


@pytest.mark.parametrize("reason", ["", "   "])
def test_reason_is_required(postgres_engine: Engine, reason: str) -> None:
    seed = Seed(postgres_engine)

    with Session(postgres_engine) as session, session.begin():
        with pytest.raises(ActionItemOperationError, match="reason"):
            seed.transfer(session, seed.owner, seed.new1, reason)

    seed.assert_untouched()


def test_new_executor_must_be_an_active_user_of_the_same_organization(
    postgres_engine: Engine,
) -> None:
    seed = Seed(postgres_engine)
    other = Seed(postgres_engine)
    seed.set_active(seed.new2, False)

    for target in (seed.new2, other.new1, UserId(uuid4())):
        with Session(postgres_engine) as session, session.begin():
            with pytest.raises(LookupError, match="Active organization User"):
                seed.transfer(session, seed.owner, target)

    seed.assert_untouched()


def test_deactivated_owner_cannot_transfer(postgres_engine: Engine) -> None:
    seed = Seed(postgres_engine)
    seed.set_active(seed.owner, False)

    with Session(postgres_engine) as session, session.begin():
        with pytest.raises(ReviewAuthorizationError):
            seed.transfer(session, seed.owner, seed.new1)

    seed.assert_untouched()


def test_transfer_is_atomic_when_the_activity_cannot_be_written(
    postgres_engine: Engine,
) -> None:
    seed = Seed(postgres_engine)

    with pytest.raises(RuntimeError, match="boom"):
        with Session(postgres_engine) as session, session.begin():
            seed.transfer(session, seed.owner, seed.new1)
            raise RuntimeError("boom")

    seed.assert_untouched()


# ---------------------------------------------------------------- double-Session races


def _waiter_is_blocked(engine: Engine) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND application_name = :name "
                    "AND wait_event_type = 'Lock' AND cardinality(pg_blocking_pids(pid)) > 0"
                ),
                {"name": WAITER},
            )
        )


def _race(
    seed: Seed,
    hold: Callable[[Session], None],
    contend: Callable[[Session], object],
) -> BaseException | None:
    """Session A runs `hold` and keeps its locks; Session B runs `contend` and must block.

    Returns what B raised (None on success) after A committed. Fails if B never blocked, so a
    race that did not really interleave cannot pass.
    """

    def session_b() -> None:
        with Session(seed.engine) as session, session.begin():
            session.execute(text(f"SET LOCAL application_name = '{WAITER}'"))
            contend(session)

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        session_a = Session(seed.engine)
        transaction = session_a.begin()
        hold(session_a)
        future = pool.submit(session_b)
        waited = False
        deadline = time.monotonic() + 10
        while not future.done() and time.monotonic() < deadline:
            if _waiter_is_blocked(seed.engine):
                waited = True
                break
            time.sleep(0.05)
        transaction.commit()
        session_a.close()
        error = future.exception(timeout=15)
        assert waited, f"Session B never blocked on Session A's lock: {error!r}"
        return error
    finally:
        pool.shutdown(wait=True)


def _deactivate(seed: Seed, user_id: UserId) -> Callable[[Session], None]:
    def run(session: Session) -> None:
        build_case_team_coordinator(session).update_user(
            seed.user(session, seed.admin), user_id, is_active=False, now=NOW
        )

    return run


def test_transfer_racing_deactivation_of_the_new_executor_is_a_409(
    postgres_engine: Engine,
) -> None:
    """Deactivation commits first: the new executor must not end up assigned."""
    seed = Seed(postgres_engine)

    error = _race(
        seed,
        _deactivate(seed, seed.new1),
        lambda session: seed.transfer(session, seed.owner, seed.new1),
    )

    assert isinstance(error, ConcurrentActionItemTransitionError), repr(error)
    seed.assert_untouched()


def test_deactivation_racing_a_transfer_waits_and_does_not_deadlock(
    postgres_engine: Engine,
) -> None:
    """Transfer commits first: the later deactivation simply applies afterwards."""
    seed = Seed(postgres_engine)

    error = _race(
        seed,
        lambda session: seed.transfer(session, seed.owner, seed.new1),
        _deactivate(seed, seed.new1),
    )

    assert error is None, repr(error)
    assert seed.action().lifecycle == "in_progress"
    assert (seed.new1, "primary") in seed.assignees()
    with Session(postgres_engine) as session:
        assert seed.user(session, seed.new1).is_active is False


def test_transfer_racing_deactivation_that_locks_users_in_id_order_does_not_deadlock(
    postgres_engine: Engine,
) -> None:
    """Deactivation of someone else locks {actor, new executor, ...} sorted by ID in one
    statement, because they share another Case; the transfer must queue behind it."""
    seed = Seed(postgres_engine)
    with Session(postgres_engine) as session, session.begin():
        other_case = uuid4()
        template = session.get(ReviewCaseRecord, seed.case_id)
        assert template is not None
        session.add(
            ReviewCaseRecord(
                id=other_case,
                organization_id=seed.organization_id,
                plan_id=None,
                scenario_version_id=template.scenario_version_id,
                title="Shared other Case",
                lifecycle="in_progress",
                planned_start_at=None,
                planned_end_at=None,
                started_at=NOW,
                fieldwork_completed_at=None,
                closed_at=None,
                scenario_data_json=template.scenario_data_json,
                created_by=seed.lead,
                created_at=NOW,
            )
        )
        session.flush()
        session.add_all(
            CaseMemberRecord(
                organization_id=seed.organization_id,
                case_id=other_case,
                user_id=user_id,
                role_key=role,
                joined_at=NOW,
            )
            for user_id, role in (
                (seed.lead, "lead"),
                (seed.owner, "observer"),
                (seed.new1, "observer"),
                (seed.bystander, "observer"),
            )
        )

    error = _race(
        seed,
        _deactivate(seed, seed.bystander),
        lambda session: seed.transfer(session, seed.owner, seed.new1),
    )

    assert error is None, repr(error)
    assert seed.action().lifecycle == "in_progress"


def test_two_transfers_race_and_exactly_one_wins(postgres_engine: Engine) -> None:
    seed = Seed(postgres_engine)

    error = _race(
        seed,
        lambda session: seed.transfer(session, seed.owner, seed.new1, "first"),
        lambda session: seed.transfer(session, seed.owner, seed.new2, "second"),
    )

    assert isinstance(error, ConcurrentActionItemTransitionError), repr(error)
    (activity,) = seed.transfer_activities()
    assert activity.metadata_json["reason"] == "first"
    assert (seed.new1, "primary") in seed.assignees()
    assert (seed.new2, "primary") not in seed.assignees()


def test_transfer_racing_reactivation_of_the_original_executor_is_a_409(
    postgres_engine: Engine,
) -> None:
    """The original primary is reactivated (uncommitted) while the transfer passed its
    pre-lock check on the committed 'all deactivated' state: after waiting, the executor is
    active again, so the command is a stale one (409) and must change nothing."""
    seed = Seed(postgres_engine)

    def reactivate(session: Session) -> None:
        build_case_team_coordinator(session).update_user(
            seed.user(session, seed.admin), seed.primary, is_active=True, now=NOW
        )

    error = _race(seed, reactivate, lambda session: seed.transfer(session, seed.owner, seed.new1))

    assert isinstance(error, ConcurrentActionItemTransitionError), repr(error)
    seed.assert_untouched()
    assert seed.assignees() == {(seed.primary, "primary")}


def test_deactivating_the_last_active_collaborator_races_the_transfer_serially(
    postgres_engine: Engine,
) -> None:
    """While the deactivation of the last active executor is uncommitted, the committed state
    still has an active executor: the transfer is refused (422, nothing blocks or changes);
    once the deactivation commits the same command succeeds."""
    seed = Seed(postgres_engine, with_collaborator=True)
    seed.set_active(seed.collaborator, True)

    session_a = Session(postgres_engine)
    transaction = session_a.begin()
    try:
        _deactivate(seed, seed.collaborator)(session_a)
        with Session(postgres_engine) as session_b, session_b.begin():
            with pytest.raises(ActionItemOperationError, match="active executor"):
                seed.transfer(session_b, seed.owner, seed.new1)
        transaction.commit()
    finally:
        session_a.close()
    seed.assert_untouched()

    seed.transfer_committed(seed.owner, seed.new1)

    assert seed.action().lifecycle == "in_progress"
    assert seed.assignees() == {(seed.new1, "primary")}


def test_transfer_racing_a_finding_status_change_is_a_409(postgres_engine: Engine) -> None:
    seed = Seed(postgres_engine)

    def submit_for_verification(session: Session) -> None:
        build_rectification_service(session).submit_rectification(
            seed.user(session, seed.owner),
            FindingId(seed.finding_id),
            "submit_for_verification",
            {"stage": "completion", "comment": "all done"},
            occurred_at=NOW,
        )

    error = _race(
        seed,
        submit_for_verification,
        lambda session: seed.transfer(session, seed.owner, seed.new1),
    )

    assert isinstance(error, ConcurrentFindingTransitionError), repr(error)
    assert seed.action().lifecycle == "done"
    assert seed.transfer_activities() == []


def test_transfer_racing_a_case_lifecycle_change_is_a_409(postgres_engine: Engine) -> None:
    seed = Seed(postgres_engine, case_lifecycle="in_progress")

    def finish_fieldwork(session: Session) -> None:
        from easyaudit_next.composition import build_review_planning_service

        build_review_planning_service(session).transition_case(
            seed.user(session, seed.lead),
            _case_id(seed),
            "finish_fieldwork",
            occurred_at=NOW,
        )

    error = _race(
        seed, finish_fieldwork, lambda session: seed.transfer(session, seed.owner, seed.new1)
    )

    assert isinstance(error, ConcurrentCaseTransitionError), repr(error)
    seed.assert_untouched()


def test_owner_deactivated_while_waiting_is_refused(postgres_engine: Engine) -> None:
    seed = Seed(postgres_engine)

    error = _race(
        seed,
        _deactivate(seed, seed.owner),
        lambda session: seed.transfer(session, seed.owner, seed.new1),
    )

    assert isinstance(error, ReviewAuthorizationError), repr(error)
    seed.assert_untouched()


def _case_id(seed: Seed) -> Any:
    from easyaudit_next.review_core.domain.ids import ReviewCaseId

    return ReviewCaseId(seed.case_id)


# ---------------------------------------------------------------- lock order


def test_lock_order_is_case_then_users_in_one_statement_then_finding(
    postgres_engine: Engine,
) -> None:
    seed = Seed(postgres_engine, with_collaborator=True)
    locks: list[tuple[str, int]] = []

    def record(_conn: Any, _cursor: Any, statement: str, parameters: Any, *_: Any) -> None:
        if "FOR NO KEY UPDATE" not in statement:
            return
        table = re.search(r"\bFROM\s+(\w+)", statement)
        assert table is not None
        # number of non-organization ids bound by the statement
        ids = [key for key in dict(parameters) if not key.startswith("organization_id")]
        locks.append((table.group(1), len(ids)))

    event.listen(postgres_engine, "before_cursor_execute", record)
    try:
        with Session(postgres_engine) as session, session.begin():
            seed.transfer(session, seed.owner, seed.new1)
    finally:
        event.remove(postgres_engine, "before_cursor_execute", record)

    tables = [table for table, _ in locks]
    assert tables[0] == "review_cases"
    first_user_lock = tables.index("users")
    # actor, new executor and both current executors: one ID-ordered statement
    assert locks[first_user_lock][1] == 4
    last_user_lock = len(tables) - 1 - tables[::-1].index("users")
    assert last_user_lock < tables.index("findings")
