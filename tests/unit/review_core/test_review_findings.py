from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from easyaudit_next.composition import build_scenario_registry
from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import Department, PlatformRole, User
from easyaudit_next.review_core.application.review_findings import (
    ConcurrentFindingTransitionError,
    FindingLifecycleService,
)
from easyaudit_next.review_core.application.review_planning import ReviewAuthorizationError
from easyaudit_next.review_core.domain.ids import FindingId, ReviewCaseId
from easyaudit_next.review_core.domain.models import (
    Activity,
    CaseMember,
    DepartmentActor,
    Finding,
    FindingLifecycle,
    FindingParticipant,
    FindingSeverity,
    ReviewCase,
    ReviewCaseLifecycle,
    ScenarioKey,
    ScenarioVersion,
    UserActor,
)

NOW = datetime(2026, 8, 24, 9, 30, tzinfo=UTC)


class InMemoryRepository:
    def __init__(self, review_case: ReviewCase, lead: User) -> None:
        self.review_case = review_case
        self.findings: dict[FindingId, Finding] = {}
        self.participants: list[FindingParticipant] = []
        self.members = [
            CaseMember(
                organization_id=review_case.organization_id,
                case_id=review_case.id,
                user_id=lead.id,
                role_key="lead",
                joined_at=NOW,
            )
        ]
        self.activities: list[Activity] = []
        self.reject_update = False

    def get_case(
        self,
        organization_id: OrganizationId,
        case_id: ReviewCaseId,
    ) -> ReviewCase | None:
        if (
            self.review_case.organization_id == organization_id
            and self.review_case.id == case_id
        ):
            return self.review_case
        return None

    def list_case_members(
        self,
        organization_id: OrganizationId,
        case_id: ReviewCaseId,
    ) -> tuple[CaseMember, ...]:
        return tuple(
            member
            for member in self.members
            if member.organization_id == organization_id and member.case_id == case_id
        )

    def add_finding(self, finding: Finding) -> None:
        self.findings[finding.id] = finding

    def get_finding(
        self,
        organization_id: OrganizationId,
        finding_id: FindingId,
    ) -> Finding | None:
        finding = self.findings.get(finding_id)
        if finding is not None and finding.organization_id == organization_id:
            return finding
        return None

    def list_findings(
        self,
        organization_id: OrganizationId,
        case_id: ReviewCaseId,
    ) -> tuple[Finding, ...]:
        return tuple(
            finding
            for finding in self.findings.values()
            if finding.organization_id == organization_id and finding.case_id == case_id
        )

    def update_finding(
        self,
        finding: Finding,
        *,
        expected_lifecycle: FindingLifecycle,
    ) -> bool:
        current = self.findings.get(finding.id)
        if (
            self.reject_update
            or current is None
            or current.lifecycle is not expected_lifecycle
        ):
            return False
        self.findings[finding.id] = finding
        return True

    def add_finding_participant(self, participant: FindingParticipant) -> None:
        self.participants.append(participant)

    def list_finding_participants(
        self,
        organization_id: OrganizationId,
        finding_id: FindingId,
    ) -> tuple[FindingParticipant, ...]:
        return tuple(
            participant
            for participant in self.participants
            if participant.organization_id == organization_id
            and participant.finding_id == finding_id
        )

    def add_activity(self, activity: Activity) -> None:
        self.activities.append(activity)


class Users:
    def __init__(self, *users: User) -> None:
        self.users = {user.id: user for user in users}

    def get(self, user_id: UserId) -> User | None:
        return self.users.get(user_id)


class Departments:
    def __init__(self, *departments: Department) -> None:
        self.departments = {department.id: department for department in departments}

    def get(self, department_id: DepartmentId) -> Department | None:
        return self.departments.get(department_id)


def _user(
    organization_id: OrganizationId,
    *,
    department_id: DepartmentId | None = None,
) -> User:
    return User(
        id=UserId(uuid4()),
        organization_id=organization_id,
        display_name="User",
        platform_role=PlatformRole.ORDINARY_USER,
        primary_department_id=department_id,
    )


def _fixture() -> tuple[
    FindingLifecycleService,
    InMemoryRepository,
    User,
    User,
    User,
    Department,
]:
    organization_id = OrganizationId(uuid4())
    department = Department(
        id=DepartmentId(uuid4()),
        organization_id=organization_id,
        name="Operations",
    )
    lead = _user(organization_id)
    owner = _user(organization_id)
    department_member = _user(organization_id, department_id=department.id)
    review_case = ReviewCase(
        id=ReviewCaseId(uuid4()),
        organization_id=organization_id,
        plan_id=None,
        scenario_key=ScenarioKey("process_review"),
        scenario_version=ScenarioVersion(1),
        title="Assembly Review",
        lifecycle=ReviewCaseLifecycle.IN_PROGRESS,
        created_by=lead.id,
        created_at=NOW,
    )
    repository = InMemoryRepository(review_case, lead)
    service = FindingLifecycleService(
        repository,  # type: ignore[arg-type]
        Users(lead, owner, department_member),  # type: ignore[arg-type]
        Departments(department),  # type: ignore[arg-type]
        build_scenario_registry(),
    )
    return service, repository, lead, owner, department_member, department


def _create_finding(
    service: FindingLifecycleService,
    lead: User,
    case_id: ReviewCaseId,
) -> Finding:
    return service.create_finding(
        lead,
        case_id,
        "Missing calibration evidence",
        FindingSeverity.HIGH,
        {"issue_type": "control_gap", "project_category": "assembly"},
        occurred_at=NOW,
    )


def _assign_required_participants(
    service: FindingLifecycleService,
    lead: User,
    finding: Finding,
    owner: User,
    department: Department,
) -> None:
    service.add_participant(lead, finding.id, UserActor(owner.id), "owner", occurred_at=NOW)
    service.add_participant(
        lead,
        finding.id,
        DepartmentActor(department.id),
        "responsible_department",
        occurred_at=NOW,
    )


def test_create_finding_validates_scenario_data_and_records_activity() -> None:
    service, repository, lead, _, _, _ = _fixture()

    with pytest.raises(ValueError, match="project_category"):
        service.create_finding(
            lead,
            repository.review_case.id,
            "Incomplete",
            FindingSeverity.MEDIUM,
            {"issue_type": "control_gap"},
        )

    finding = _create_finding(service, lead, repository.review_case.id)

    assert finding.lifecycle is FindingLifecycle.OPEN
    assert finding.scenario_data["issue_type"] == "control_gap"
    assert repository.activities[-1].event_type == "finding.created"


@pytest.mark.parametrize(
    "lifecycle",
    [
        ReviewCaseLifecycle.DRAFT,
        ReviewCaseLifecycle.SCHEDULED,
        ReviewCaseLifecycle.AWAITING_CLOSURE,
        ReviewCaseLifecycle.CLOSED,
        ReviewCaseLifecycle.CANCELLED,
    ],
)
def test_create_finding_requires_in_progress_case(lifecycle: ReviewCaseLifecycle) -> None:
    service, repository, lead, _, _, _ = _fixture()
    repository.review_case = replace(repository.review_case, lifecycle=lifecycle)

    with pytest.raises(ValueError, match="only be created.*in_progress"):
        _create_finding(service, lead, repository.review_case.id)


def test_participant_role_enforces_actor_kind_and_same_organization() -> None:
    service, repository, lead, owner, _, department = _fixture()
    finding = _create_finding(service, lead, repository.review_case.id)

    with pytest.raises(ValueError, match="owner.*department"):
        service.add_participant(
            lead,
            finding.id,
            DepartmentActor(department.id),
            "owner",
        )
    with pytest.raises(ValueError, match="responsible_department.*user"):
        service.add_participant(
            lead,
            finding.id,
            UserActor(owner.id),
            "responsible_department",
        )

    foreign_user = UserActor(UserId(uuid4()))
    with pytest.raises(LookupError, match="organization User"):
        service.add_participant(lead, finding.id, foreign_user, "owner")

    service.add_participant(lead, finding.id, UserActor(owner.id), "owner")
    service.add_participant(
        lead,
        finding.id,
        DepartmentActor(department.id),
        "responsible_department",
    )
    assert len(repository.participants) == 2


def test_direct_and_department_participants_gain_visibility_but_not_write_authority() -> None:
    service, repository, lead, owner, department_member, department = _fixture()
    finding = _create_finding(service, lead, repository.review_case.id)
    _assign_required_participants(service, lead, finding, owner, department)

    assert service.get_finding(owner, finding.id) == finding
    assert service.get_finding(department_member, finding.id) == finding
    with pytest.raises(ReviewAuthorizationError, match="lead or auditor"):
        service.transition_finding(department_member, finding.id, "issue")


def test_issue_requires_owner_and_responsible_department() -> None:
    service, repository, lead, owner, _, department = _fixture()
    finding = _create_finding(service, lead, repository.review_case.id)

    with pytest.raises(ValueError, match="responsible_department, owner"):
        service.transition_finding(lead, finding.id, "issue")

    service.add_participant(lead, finding.id, UserActor(owner.id), "owner")
    with pytest.raises(ValueError, match="responsible_department"):
        service.transition_finding(lead, finding.id, "issue")

    service.add_participant(
        lead,
        finding.id,
        DepartmentActor(department.id),
        "responsible_department",
    )
    issued = service.transition_finding(lead, finding.id, "issue", occurred_at=NOW)
    assert issued.lifecycle is FindingLifecycle.RECTIFYING


def test_issue_is_explicitly_allowed_for_existing_open_finding_awaiting_closure() -> None:
    service, repository, lead, owner, _, department = _fixture()
    finding = _create_finding(service, lead, repository.review_case.id)
    _assign_required_participants(service, lead, finding, owner, department)
    repository.review_case = replace(
        repository.review_case,
        lifecycle=ReviewCaseLifecycle.AWAITING_CLOSURE,
    )

    issued = service.transition_finding(lead, finding.id, "issue", occurred_at=NOW)
    assert issued.lifecycle is FindingLifecycle.RECTIFYING


def test_issue_and_void_are_scenario_transitions_and_void_requires_reason() -> None:
    service, repository, lead, owner, _, department = _fixture()
    issue_finding = _create_finding(service, lead, repository.review_case.id)
    _assign_required_participants(service, lead, issue_finding, owner, department)
    issued = service.transition_finding(lead, issue_finding.id, "issue", occurred_at=NOW)
    assert issued.lifecycle is FindingLifecycle.RECTIFYING
    with pytest.raises(ValueError, match="M2.3 only supports"):
        service.transition_finding(lead, issue_finding.id, "submit_for_verification")

    void_finding = service.create_finding(
        lead,
        issue_finding.case_id,
        "Duplicate observation",
        FindingSeverity.LOW,
        {"issue_type": "duplicate", "project_category": "assembly"},
        occurred_at=NOW,
    )
    with pytest.raises(ValueError, match="requires a reason"):
        service.transition_finding(lead, void_finding.id, "void")
    voided = service.transition_finding(
        lead,
        void_finding.id,
        "void",
        reason="Duplicate of existing Finding",
        occurred_at=NOW,
    )
    assert voided.lifecycle is FindingLifecycle.VOIDED


def test_terminal_finding_freezes_participant_management() -> None:
    service, repository, lead, owner, _, _ = _fixture()
    finding = _create_finding(service, lead, repository.review_case.id)
    voided = service.transition_finding(
        lead,
        finding.id,
        "void",
        reason="Duplicate",
        occurred_at=NOW,
    )
    assert voided.lifecycle is FindingLifecycle.VOIDED

    with pytest.raises(ValueError, match="Terminal Finding participants"):
        service.add_participant(lead, finding.id, UserActor(owner.id), "owner")


def test_transition_reports_conflict_when_lifecycle_cas_loses() -> None:
    service, repository, lead, owner, _, department = _fixture()
    finding = _create_finding(service, lead, repository.review_case.id)
    _assign_required_participants(service, lead, finding, owner, department)
    repository.reject_update = True

    with pytest.raises(ConcurrentFindingTransitionError):
        service.transition_finding(lead, finding.id, "issue")

    assert all(activity.event_type != "finding.transitioned" for activity in repository.activities)
