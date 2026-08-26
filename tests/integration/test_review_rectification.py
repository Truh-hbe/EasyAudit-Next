import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, delete, func, inspect, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from easyaudit_next.composition import (
    build_finding_lifecycle_service,
    build_rectification_service,
    build_review_planning_service,
    build_scenario_registry,
)
from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.persistence.models import (
    DepartmentRecord,
    OrganizationRecord,
    UserRecord,
)
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyDepartmentRepository,
    SqlAlchemyUserRepository,
)
from easyaudit_next.review_core.application.review_findings import (
    ConcurrentFindingTransitionError,
)
from easyaudit_next.review_core.application.review_planning import ReviewAuthorizationError
from easyaudit_next.review_core.application.review_rectification import (
    ConcurrentActionItemTransitionError,
    RectificationService,
)
from easyaudit_next.review_core.domain.models import (
    ActionItemLifecycle,
    AssignmentRole,
    DepartmentActor,
    FindingLifecycle,
    FindingSeverity,
    ScenarioKey,
    ScenarioVersion,
    UserActor,
)
from easyaudit_next.review_core.persistence.models import (
    ActionItemRecord,
    ActivityRecord,
    EvidenceRecord,
    FindingRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
    SubmissionRecord,
)
from easyaudit_next.review_core.persistence.rectification_repositories import (
    SqlAlchemyRectificationRepository,
)

NOW = datetime(2026, 8, 26, 14, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _seed_process_review(
    engine: Engine,
) -> tuple[OrganizationId, DepartmentId, UserId, UserId]:
    organization_id = OrganizationId(uuid4())
    department_id = DepartmentId(uuid4())
    lead_id = UserId(uuid4())
    owner_id = UserId(uuid4())
    scenario_id = uuid4()
    with Session(engine) as session, session.begin():
        session.add(
            OrganizationRecord(
                id=organization_id,
                name=f"M2.4 {organization_id}",
            )
        )
        session.flush()
        session.add(
            DepartmentRecord(
                id=department_id,
                organization_id=organization_id,
                name="Operations",
            )
        )
        session.flush()
        session.add_all(
            [
                UserRecord(
                    id=lead_id,
                    organization_id=organization_id,
                    display_name="Rectification Lead",
                    platform_role="ordinary_user",
                ),
                UserRecord(
                    id=owner_id,
                    organization_id=organization_id,
                    primary_department_id=department_id,
                    display_name="Rectification Owner",
                    platform_role="ordinary_user",
                ),
            ]
        )
        session.flush()
        session.add(
            ScenarioRecord(
                id=scenario_id,
                organization_id=organization_id,
                key="process_review",
                name="Process Review",
            )
        )
        session.flush()
        session.add(
            ScenarioVersionRecord(
                id=uuid4(),
                scenario_id=scenario_id,
                organization_id=organization_id,
                version=1,
                published_at=NOW,
            )
        )
    return organization_id, department_id, lead_id, owner_id


def _rectification_service(
    session: Session,
    repository: SqlAlchemyRectificationRepository | None = None,
) -> RectificationService:
    return RectificationService(
        repository or SqlAlchemyRectificationRepository(session),
        SqlAlchemyUserRepository(session),
        SqlAlchemyDepartmentRepository(session),
        build_scenario_registry(),
    )


def _create_rectifying_finding(
    session: Session,
    lead_id: UserId,
    owner_id: UserId,
    department_id: DepartmentId,
):
    users = SqlAlchemyUserRepository(session)
    lead = users.get(lead_id)
    owner = users.get(owner_id)
    assert lead is not None and owner is not None

    planning = build_review_planning_service(session)
    review_case = planning.create_case(
        lead,
        ScenarioKey("process_review"),
        ScenarioVersion(1),
        f"M2.4 Case {uuid4()}",
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
        "Calibration evidence is missing",
        FindingSeverity.HIGH,
        {"issue_type": "control_gap", "project_category": "assembly"},
        occurred_at=NOW,
    )
    findings.add_participant(
        lead,
        finding.id,
        UserActor(owner.id),
        "owner",
        occurred_at=NOW,
    )
    findings.add_participant(
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
    assert finding.lifecycle is FindingLifecycle.RECTIFYING
    return finding, owner


def _create_assigned_action(session: Session, owner_id: UserId, finding_id):
    owner = SqlAlchemyUserRepository(session).get(owner_id)
    assert owner is not None
    service = build_rectification_service(session)
    action_item = service.create_action_item(
        owner,
        finding_id,
        "Update calibration status card",
        occurred_at=NOW,
    )
    service.add_assignee(
        owner,
        action_item.id,
        UserActor(owner.id),
        AssignmentRole.PRIMARY,
        occurred_at=NOW,
    )
    return service, owner, action_item


def _complete_action(service: RectificationService, owner, action_item):
    action_item = service.transition_action_item(
        owner,
        action_item.id,
        "start",
        occurred_at=NOW,
    )
    return service.transition_action_item(
        owner,
        action_item.id,
        "complete",
        occurred_at=NOW,
    )


def test_m2_4_migration_adds_action_completion_and_evidence_table(
    postgres_engine: Engine,
) -> None:
    action_columns = {
        column["name"] for column in inspect(postgres_engine).get_columns("action_items")
    }
    evidence_columns = {
        column["name"] for column in inspect(postgres_engine).get_columns("evidences")
    }
    assert "completed_at" in action_columns
    assert {
        "id",
        "organization_id",
        "action_item_id",
        "storage_key",
        "original_name",
        "sha256",
        "uploaded_by",
        "created_at",
    }.issubset(evidence_columns)


def test_real_rectification_chain_persists_evidence_and_reaches_verifying(
    postgres_engine: Engine,
) -> None:
    organization_id, department_id, lead_id, owner_id = _seed_process_review(postgres_engine)
    with Session(postgres_engine, expire_on_commit=False) as session:
        finding, owner = _create_rectifying_finding(
            session,
            lead_id,
            owner_id,
            department_id,
        )
        service, _, action_item = _create_assigned_action(session, owner_id, finding.id)
        action_item = _complete_action(service, owner, action_item)
        assert action_item.lifecycle is ActionItemLifecycle.DONE
        assert action_item.completed_at == NOW

        evidence = service.register_evidence(
            owner,
            action_item.id,
            "review-evidence/calibration-status.jpg",
            "calibration-status.jpg",
            2048,
            "a" * 64,
            content_type="image/jpeg",
            description="Updated status card after rectification",
            occurred_at=NOW,
        )
        plan_submission, plan_finding = service.submit_rectification(
            owner,
            finding.id,
            "submit_plan",
            {"stage": "plan", "root_cause": "Status card was not updated after changeover"},
            occurred_at=NOW,
        )
        assert plan_finding.lifecycle is FindingLifecycle.RECTIFYING

        completion_submission, completed_finding = service.submit_rectification(
            owner,
            finding.id,
            "submit_for_verification",
            {"stage": "completion", "comment": "Action completed with evidence"},
            occurred_at=NOW,
        )
        assert completed_finding.lifecycle is FindingLifecycle.VERIFYING
        session.commit()

    with Session(postgres_engine) as verification:
        action_record = verification.scalar(
            select(ActionItemRecord).where(
                ActionItemRecord.organization_id == organization_id,
                ActionItemRecord.id == action_item.id,
            )
        )
        evidence_record = verification.scalar(
            select(EvidenceRecord).where(EvidenceRecord.id == evidence.id)
        )
        finding_record = verification.scalar(
            select(FindingRecord).where(FindingRecord.id == finding.id)
        )
        submissions = tuple(
            verification.scalars(
                select(SubmissionRecord)
                .where(
                    SubmissionRecord.organization_id == organization_id,
                    SubmissionRecord.finding_id == finding.id,
                )
                .order_by(SubmissionRecord.submitted_at, SubmissionRecord.id)
            )
        )
        submission_activity_count = verification.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(
                ActivityRecord.organization_id == organization_id,
                ActivityRecord.submission_id.in_(
                    [plan_submission.id, completion_submission.id]
                ),
            )
        )
        assert action_record is not None
        assert action_record.lifecycle == "done"
        assert action_record.completed_at == NOW
        assert evidence_record is not None
        assert evidence_record.action_item_id == action_item.id
        assert evidence_record.sha256 == "a" * 64
        assert finding_record is not None
        assert finding_record.lifecycle == "verifying"
        assert len(submissions) == 2
        assert {submission.payload_json["stage"] for submission in submissions} == {
            "plan",
            "completion",
        }
        assert submission_activity_count == 2


def test_completion_submission_uses_real_non_cancelled_action_state(
    postgres_engine: Engine,
) -> None:
    _, department_id, lead_id, owner_id = _seed_process_review(postgres_engine)
    with Session(postgres_engine, expire_on_commit=False) as session:
        finding, owner = _create_rectifying_finding(
            session,
            lead_id,
            owner_id,
            department_id,
        )
        service = build_rectification_service(session)
        completion = {"stage": "completion", "comment": "Ready for verification"}

        with pytest.raises(ValueError, match="at least one non-cancelled ActionItem"):
            service.submit_rectification(
                owner,
                finding.id,
                "submit_for_verification",
                completion,
                occurred_at=NOW,
            )

        _, _, action_item = _create_assigned_action(session, owner_id, finding.id)
        with pytest.raises(ValueError, match="must be done"):
            service.submit_rectification(
                owner,
                finding.id,
                "submit_for_verification",
                completion,
                occurred_at=NOW,
            )

        _complete_action(service, owner, action_item)
        _, updated = service.submit_rectification(
            owner,
            finding.id,
            "submit_for_verification",
            completion,
            occurred_at=NOW,
        )
        assert updated.lifecycle is FindingLifecycle.VERIFYING
        session.commit()


def test_submission_checks_visibility_before_completion_business_validation(
    postgres_engine: Engine,
) -> None:
    organization_id, department_id, lead_id, owner_id = _seed_process_review(postgres_engine)
    outsider_id = UserId(uuid4())
    with Session(postgres_engine, expire_on_commit=False) as setup:
        finding, _ = _create_rectifying_finding(
            setup,
            lead_id,
            owner_id,
            department_id,
        )
        setup.add(
            UserRecord(
                id=outsider_id,
                organization_id=organization_id,
                display_name="Unrelated User",
                platform_role="ordinary_user",
            )
        )
        setup.commit()

    with Session(postgres_engine) as session:
        outsider = SqlAlchemyUserRepository(session).get(outsider_id)
        assert outsider is not None
        service = build_rectification_service(session)
        with pytest.raises(ReviewAuthorizationError, match="not visible"):
            service.submit_rectification(
                outsider,
                finding.id,
                "submit_for_verification",
                {"stage": "completion", "comment": "Should not expose state"},
                occurred_at=NOW,
            )


class _SynchronizedFindingGuardRepository(SqlAlchemyRectificationRepository):
    def __init__(self, session: Session, barrier: Barrier) -> None:
        super().__init__(session)
        self._barrier = barrier

    def lock_finding_for_rectification(self, organization_id, finding_id):
        self._barrier.wait(timeout=10)
        return super().lock_finding_for_rectification(organization_id, finding_id)


def test_concurrent_action_transition_allows_only_one_old_state_to_advance(
    postgres_engine: Engine,
) -> None:
    organization_id, department_id, lead_id, owner_id = _seed_process_review(postgres_engine)
    with Session(postgres_engine, expire_on_commit=False) as setup:
        finding, _ = _create_rectifying_finding(
            setup,
            lead_id,
            owner_id,
            department_id,
        )
        _, _, action_item = _create_assigned_action(setup, owner_id, finding.id)
        action_id = action_item.id
        setup.commit()

    barrier = Barrier(2)

    def attempt_start() -> str:
        with Session(postgres_engine, expire_on_commit=False) as session:
            owner = SqlAlchemyUserRepository(session).get(owner_id)
            assert owner is not None
            repository = _SynchronizedFindingGuardRepository(session, barrier)
            service = _rectification_service(session, repository)
            try:
                service.transition_action_item(
                    owner,
                    action_id,
                    "start",
                    occurred_at=NOW,
                )
                session.commit()
            except ConcurrentActionItemTransitionError:
                session.rollback()
                return "conflict"
            return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(
            future.result()
            for future in [executor.submit(attempt_start) for _ in range(2)]
        )

    assert outcomes == ["conflict", "success"]
    with Session(postgres_engine) as verification:
        persisted = verification.scalar(
            select(ActionItemRecord).where(
                ActionItemRecord.organization_id == organization_id,
                ActionItemRecord.id == action_id,
            )
        )
        transition_count = verification.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(
                ActivityRecord.organization_id == organization_id,
                ActivityRecord.action_item_id == action_id,
                ActivityRecord.event_type == "action_item.transitioned",
            )
        )
        assert persisted is not None
        assert persisted.lifecycle == "in_progress"
        assert transition_count == 1


def test_concurrent_completion_submission_creates_one_snapshot_and_one_transition(
    postgres_engine: Engine,
) -> None:
    organization_id, department_id, lead_id, owner_id = _seed_process_review(postgres_engine)
    with Session(postgres_engine, expire_on_commit=False) as setup:
        finding, owner = _create_rectifying_finding(
            setup,
            lead_id,
            owner_id,
            department_id,
        )
        service, _, action_item = _create_assigned_action(setup, owner_id, finding.id)
        _complete_action(service, owner, action_item)
        finding_id = finding.id
        setup.commit()

    barrier = Barrier(2)

    def attempt_completion() -> str:
        with Session(postgres_engine, expire_on_commit=False) as session:
            owner = SqlAlchemyUserRepository(session).get(owner_id)
            assert owner is not None
            repository = _SynchronizedFindingGuardRepository(session, barrier)
            service = _rectification_service(session, repository)
            try:
                service.submit_rectification(
                    owner,
                    finding_id,
                    "submit_for_verification",
                    {"stage": "completion", "comment": "Concurrent completion"},
                    occurred_at=NOW,
                )
                session.commit()
            except ConcurrentFindingTransitionError:
                session.rollback()
                return "conflict"
            return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(
            future.result()
            for future in [executor.submit(attempt_completion) for _ in range(2)]
        )

    assert outcomes == ["conflict", "success"]
    with Session(postgres_engine) as verification:
        persisted = verification.scalar(
            select(FindingRecord).where(
                FindingRecord.organization_id == organization_id,
                FindingRecord.id == finding_id,
            )
        )
        submission_count = verification.scalar(
            select(func.count())
            .select_from(SubmissionRecord)
            .where(
                SubmissionRecord.organization_id == organization_id,
                SubmissionRecord.finding_id == finding_id,
                SubmissionRecord.purpose == "rectification",
                SubmissionRecord.payload_json["stage"].as_string() == "completion",
            )
        )
        activity_count = verification.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .join(
                SubmissionRecord,
                SubmissionRecord.id == ActivityRecord.submission_id,
            )
            .where(
                ActivityRecord.organization_id == organization_id,
                SubmissionRecord.finding_id == finding_id,
                ActivityRecord.event_type == "finding.submitted_for_verification",
            )
        )
        assert persisted is not None
        assert persisted.lifecycle == "verifying"
        assert submission_count == 1
        assert activity_count == 1


def test_completion_racing_done_action_reopen_cannot_break_verifying_invariant(
    postgres_engine: Engine,
) -> None:
    organization_id, department_id, lead_id, owner_id = _seed_process_review(postgres_engine)
    with Session(postgres_engine, expire_on_commit=False) as setup:
        finding, owner = _create_rectifying_finding(
            setup,
            lead_id,
            owner_id,
            department_id,
        )
        service, _, action_item = _create_assigned_action(setup, owner_id, finding.id)
        action_item = _complete_action(service, owner, action_item)
        finding_id = finding.id
        action_id = action_item.id
        setup.commit()

    barrier = Barrier(2)

    def attempt_completion() -> str:
        with Session(postgres_engine, expire_on_commit=False) as session:
            owner = SqlAlchemyUserRepository(session).get(owner_id)
            assert owner is not None
            service = _rectification_service(
                session,
                _SynchronizedFindingGuardRepository(session, barrier),
            )
            try:
                service.submit_rectification(
                    owner,
                    finding_id,
                    "submit_for_verification",
                    {"stage": "completion", "comment": "Race with reopen"},
                    occurred_at=NOW,
                )
                session.commit()
                return "completion_success"
            except ConcurrentFindingTransitionError:
                session.rollback()
                return "completion_conflict"
            except ValueError:
                session.rollback()
                return "completion_invalid"

    def attempt_reopen() -> str:
        with Session(postgres_engine, expire_on_commit=False) as session:
            owner = SqlAlchemyUserRepository(session).get(owner_id)
            assert owner is not None
            service = _rectification_service(
                session,
                _SynchronizedFindingGuardRepository(session, barrier),
            )
            try:
                service.transition_action_item(
                    owner,
                    action_id,
                    "reopen",
                    occurred_at=NOW,
                )
                session.commit()
                return "reopen_success"
            except ConcurrentFindingTransitionError:
                session.rollback()
                return "reopen_conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = {
            executor.submit(attempt_completion).result(),
            executor.submit(attempt_reopen).result(),
        }

    assert outcomes in (
        {"completion_success", "reopen_conflict"},
        {"completion_invalid", "reopen_success"},
    )
    with Session(postgres_engine) as verification:
        finding_lifecycle = verification.scalar(
            select(FindingRecord.lifecycle).where(
                FindingRecord.organization_id == organization_id,
                FindingRecord.id == finding_id,
            )
        )
        action_lifecycle = verification.scalar(
            select(ActionItemRecord.lifecycle).where(
                ActionItemRecord.organization_id == organization_id,
                ActionItemRecord.id == action_id,
            )
        )
        completion_count = verification.scalar(
            select(func.count())
            .select_from(SubmissionRecord)
            .where(
                SubmissionRecord.organization_id == organization_id,
                SubmissionRecord.finding_id == finding_id,
                SubmissionRecord.payload_json["stage"].as_string() == "completion",
            )
        )
        assert (finding_lifecycle, action_lifecycle) != ("verifying", "in_progress")
        if finding_lifecycle == "verifying":
            assert action_lifecycle == "done"
            assert completion_count == 1
        else:
            assert finding_lifecycle == "rectifying"
            assert action_lifecycle == "in_progress"
            assert completion_count == 0


def test_completion_racing_action_create_cannot_admit_new_todo_after_cutover(
    postgres_engine: Engine,
) -> None:
    organization_id, department_id, lead_id, owner_id = _seed_process_review(postgres_engine)
    with Session(postgres_engine, expire_on_commit=False) as setup:
        finding, owner = _create_rectifying_finding(
            setup,
            lead_id,
            owner_id,
            department_id,
        )
        service, _, action_item = _create_assigned_action(setup, owner_id, finding.id)
        _complete_action(service, owner, action_item)
        finding_id = finding.id
        setup.commit()

    barrier = Barrier(2)

    def attempt_completion() -> str:
        with Session(postgres_engine, expire_on_commit=False) as session:
            owner = SqlAlchemyUserRepository(session).get(owner_id)
            assert owner is not None
            service = _rectification_service(
                session,
                _SynchronizedFindingGuardRepository(session, barrier),
            )
            try:
                service.submit_rectification(
                    owner,
                    finding_id,
                    "submit_for_verification",
                    {"stage": "completion", "comment": "Race with Action create"},
                    occurred_at=NOW,
                )
                session.commit()
                return "completion_success"
            except ConcurrentFindingTransitionError:
                session.rollback()
                return "completion_conflict"
            except ValueError:
                session.rollback()
                return "completion_invalid"

    def attempt_create() -> str:
        with Session(postgres_engine, expire_on_commit=False) as session:
            owner = SqlAlchemyUserRepository(session).get(owner_id)
            assert owner is not None
            service = _rectification_service(
                session,
                _SynchronizedFindingGuardRepository(session, barrier),
            )
            try:
                service.create_action_item(
                    owner,
                    finding_id,
                    "Concurrent new Action",
                    occurred_at=NOW,
                )
                session.commit()
                return "create_success"
            except ConcurrentFindingTransitionError:
                session.rollback()
                return "create_conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        completion_future = executor.submit(attempt_completion)
        create_future = executor.submit(attempt_create)
        outcomes = {completion_future.result(), create_future.result()}

    assert outcomes in (
        {"completion_success", "create_conflict"},
        {"completion_invalid", "create_success"},
    )
    with Session(postgres_engine) as verification:
        finding_lifecycle = verification.scalar(
            select(FindingRecord.lifecycle).where(
                FindingRecord.organization_id == organization_id,
                FindingRecord.id == finding_id,
            )
        )
        action_lifecycles = tuple(
            verification.scalars(
                select(ActionItemRecord.lifecycle)
                .where(
                    ActionItemRecord.organization_id == organization_id,
                    ActionItemRecord.finding_id == finding_id,
                )
                .order_by(ActionItemRecord.lifecycle)
            )
        )
        completion_count = verification.scalar(
            select(func.count())
            .select_from(SubmissionRecord)
            .where(
                SubmissionRecord.organization_id == organization_id,
                SubmissionRecord.finding_id == finding_id,
                SubmissionRecord.payload_json["stage"].as_string() == "completion",
            )
        )
        if finding_lifecycle == "verifying":
            assert action_lifecycles == ("done",)
            assert completion_count == 1
        else:
            assert finding_lifecycle == "rectifying"
            assert sorted(action_lifecycles) == ["done", "todo"]
            assert completion_count == 0


class _RejectSubmissionRepository(SqlAlchemyRectificationRepository):
    """Fail a formal Submission after the Finding CAS has already flushed."""

    def add_submission(self, submission) -> None:
        self._session.add(
            SubmissionRecord(
                id=submission.id,
                organization_id=submission.organization_id,
                case_id=submission.case_id,
                finding_id=submission.finding_id,
                purpose="invalid-purpose",
                submitted_by=submission.submitted_by,
                submitted_at=submission.submitted_at,
                payload_json=dict(submission.payload),
            )
        )
        self._session.flush()


def test_completion_submission_failure_rolls_back_finding_cas_and_snapshot(
    postgres_engine: Engine,
) -> None:
    organization_id, department_id, lead_id, owner_id = _seed_process_review(postgres_engine)
    with Session(postgres_engine, expire_on_commit=False) as setup:
        finding, owner = _create_rectifying_finding(
            setup,
            lead_id,
            owner_id,
            department_id,
        )
        service, _, action_item = _create_assigned_action(setup, owner_id, finding.id)
        _complete_action(service, owner, action_item)
        finding_id = finding.id
        setup.commit()

    with pytest.raises(IntegrityError):
        with Session(postgres_engine) as session, session.begin():
            owner = SqlAlchemyUserRepository(session).get(owner_id)
            assert owner is not None
            service = _rectification_service(
                session,
                _RejectSubmissionRepository(session),
            )
            service.submit_rectification(
                owner,
                finding_id,
                "submit_for_verification",
                {"stage": "completion", "comment": "Should roll back"},
                occurred_at=NOW,
            )

    with Session(postgres_engine) as verification:
        persisted = verification.scalar(
            select(FindingRecord).where(
                FindingRecord.organization_id == organization_id,
                FindingRecord.id == finding_id,
            )
        )
        submission_count = verification.scalar(
            select(func.count())
            .select_from(SubmissionRecord)
            .where(
                SubmissionRecord.organization_id == organization_id,
                SubmissionRecord.finding_id == finding_id,
            )
        )
        assert persisted is not None
        assert persisted.lifecycle == "rectifying"
        assert submission_count == 0


@pytest.mark.parametrize("statement", ["update", "delete"])
def test_evidence_is_database_append_only(
    postgres_engine: Engine,
    statement: str,
) -> None:
    _, department_id, lead_id, owner_id = _seed_process_review(postgres_engine)
    with Session(postgres_engine, expire_on_commit=False) as setup:
        finding, owner = _create_rectifying_finding(
            setup,
            lead_id,
            owner_id,
            department_id,
        )
        service, _, action_item = _create_assigned_action(setup, owner_id, finding.id)
        evidence = service.register_evidence(
            owner,
            action_item.id,
            f"evidence/{uuid4()}.txt",
            "evidence.txt",
            12,
            "b" * 64,
            content_type="text/plain",
            occurred_at=NOW,
        )
        evidence_id = evidence.id
        setup.commit()

    with Session(postgres_engine) as session:
        command = (
            update(EvidenceRecord)
            .where(EvidenceRecord.id == evidence_id)
            .values(description="tampered")
            if statement == "update"
            else delete(EvidenceRecord).where(EvidenceRecord.id == evidence_id)
        )
        with pytest.raises(DBAPIError, match="evidences are append-only"):
            session.execute(command)


@pytest.mark.parametrize("statement", ["update", "delete"])
def test_submission_is_database_append_only(
    postgres_engine: Engine,
    statement: str,
) -> None:
    _, department_id, lead_id, owner_id = _seed_process_review(postgres_engine)
    with Session(postgres_engine, expire_on_commit=False) as setup:
        finding, owner = _create_rectifying_finding(
            setup,
            lead_id,
            owner_id,
            department_id,
        )
        service = build_rectification_service(setup)
        submission, _ = service.submit_rectification(
            owner,
            finding.id,
            "submit_plan",
            {"stage": "plan", "root_cause": "Immutable formal snapshot"},
            occurred_at=NOW,
        )
        submission_id = submission.id
        setup.commit()

    with Session(postgres_engine) as session:
        command = (
            update(SubmissionRecord)
            .where(SubmissionRecord.id == submission_id)
            .values(payload_json={"tampered": True})
            if statement == "update"
            else delete(SubmissionRecord).where(SubmissionRecord.id == submission_id)
        )
        with pytest.raises(DBAPIError, match="submissions are append-only"):
            session.execute(command)
