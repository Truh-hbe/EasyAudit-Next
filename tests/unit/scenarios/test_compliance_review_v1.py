from datetime import UTC, datetime
from uuid import uuid4

import pytest

from easyaudit_next.composition import build_scenario_registry
from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import PlatformRole, User
from easyaudit_next.review_core.application.review_findings import FindingLifecycleService
from easyaudit_next.review_core.application.review_planning import ReviewAuthorizationError
from easyaudit_next.review_core.domain.ids import FindingId, ReviewCaseId
from easyaudit_next.review_core.domain.models import (
    Activity,
    CaseMember,
    Finding,
    FindingLifecycle,
    FindingParticipant,
    FindingSeverity,
    ReviewCase,
    ReviewCaseLifecycle,
    ScenarioKey,
    ScenarioVersion,
)
from easyaudit_next.review_core.domain.scenario_capabilities import FindingOperationContext
from easyaudit_next.scenarios.compliance_review import (
    COMPLIANCE_REVIEW_V1,
    ComplianceReviewPermission,
)

NOW = datetime(2026, 8, 29, 10, 30, tzinfo=UTC)


class Repository:
    def __init__(self, review_case: ReviewCase, lead: User, reviewer: User) -> None:
        self.review_case = review_case
        self.findings: dict[FindingId, Finding] = {}
        self.members = [
            CaseMember(
                organization_id=review_case.organization_id,
                case_id=review_case.id,
                user_id=lead.id,
                role_key="lead",
                joined_at=NOW,
            ),
            CaseMember(
                organization_id=review_case.organization_id,
                case_id=review_case.id,
                user_id=reviewer.id,
                role_key="reviewer",
                joined_at=NOW,
            ),
        ]
        self.activities: list[Activity] = []

    def get_case(
        self,
        organization_id: OrganizationId,
        case_id: ReviewCaseId,
    ) -> ReviewCase | None:
        if self.review_case.organization_id == organization_id and self.review_case.id == case_id:
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
        if current is None or current.lifecycle is not expected_lifecycle:
            return False
        self.findings[finding.id] = finding
        return True

    def list_finding_participants(
        self,
        organization_id: OrganizationId,
        finding_id: FindingId,
    ) -> tuple[FindingParticipant, ...]:
        return ()

    def add_activity(self, activity: Activity) -> None:
        self.activities.append(activity)


class Users:
    def get(self, user_id: UserId) -> User | None:
        return None


class Departments:
    def get(self, department_id: DepartmentId) -> None:
        return None


def _user(organization_id: OrganizationId) -> User:
    return User(
        id=UserId(uuid4()),
        organization_id=organization_id,
        display_name="User",
        platform_role=PlatformRole.ORDINARY_USER,
    )


def _finding_service(repository: Repository) -> FindingLifecycleService:
    return FindingLifecycleService(
        repository,  # type: ignore[arg-type]
        Users(),  # type: ignore[arg-type]
        Departments(),  # type: ignore[arg-type]
        build_scenario_registry(),
    )


def _service() -> tuple[FindingLifecycleService, Repository, User, User]:
    organization_id = OrganizationId(uuid4())
    lead = _user(organization_id)
    reviewer = _user(organization_id)
    review_case = ReviewCase(
        id=ReviewCaseId(uuid4()),
        organization_id=organization_id,
        plan_id=None,
        scenario_key=ScenarioKey("compliance_review"),
        scenario_version=ScenarioVersion(1),
        title="ISO 9001 compliance review",
        lifecycle=ReviewCaseLifecycle.IN_PROGRESS,
        created_by=lead.id,
        created_at=NOW,
        scenario_data={
            "standard_reference": "ISO 9001:2015",
            "scope_summary": "Assembly control",
        },
    )
    repository = Repository(review_case, lead, reviewer)
    return _finding_service(repository), repository, lead, reviewer


def test_registry_registers_exact_compliance_policy() -> None:
    registry = build_scenario_registry()

    assert (
        registry.get(ScenarioKey("compliance_review"), ScenarioVersion(1))
        is COMPLIANCE_REVIEW_V1
    )


def test_compliance_scenario_data_validation_is_exact_and_version_owned() -> None:
    assert COMPLIANCE_REVIEW_V1.validate_case_input(
        {"standard_reference": "ISO 9001:2015", "scope_summary": "Assembly"}
    ) == ()
    assert COMPLIANCE_REVIEW_V1.validate_finding_input(
        {"criterion_reference": "8.5.1", "finding_type": "observation"}
    ) == ()
    assert COMPLIANCE_REVIEW_V1.validate_finding_input(
        {"criterion_reference": "8.5.1", "finding_type": "nonconformity"}
    ) == ()
    assert "finding_type must be 'nonconformity' or 'observation'" in (
        COMPLIANCE_REVIEW_V1.validate_finding_input(
            {"criterion_reference": "8.5.1", "finding_type": "note"}
        )
    )


def test_changing_only_finding_type_changes_exact_direct_transition_policy() -> None:
    policy = COMPLIANCE_REVIEW_V1.finding_direct_transitions
    base = dict(
        case_lifecycle=ReviewCaseLifecycle.IN_PROGRESS,
        current_finding_lifecycle=FindingLifecycle.OPEN,
    )

    observation = policy.decide(
        "accept_observation",
        FindingOperationContext(
            **base,
            scenario_data={"finding_type": "observation"},
        ),
    )
    assert observation.required_permission == ComplianceReviewPermission.ACCEPT_OBSERVATION
    assert observation.target_lifecycle is FindingLifecycle.CLOSED

    with pytest.raises(ValueError, match="Only an observation"):
        policy.decide(
            "accept_observation",
            FindingOperationContext(
                **base,
                scenario_data={"finding_type": "nonconformity"},
            ),
        )


def test_nonconformity_issue_requires_real_remediation_responsibility() -> None:
    policy = COMPLIANCE_REVIEW_V1.finding_direct_transitions
    base = dict(
        case_lifecycle=ReviewCaseLifecycle.IN_PROGRESS,
        current_finding_lifecycle=FindingLifecycle.OPEN,
        scenario_data={"finding_type": "nonconformity"},
    )

    with pytest.raises(ValueError, match="responsible_department, owner"):
        policy.decide("issue", FindingOperationContext(**base))

    issued = policy.decide(
        "issue",
        FindingOperationContext(
            **base,
            participant_role_keys=frozenset({"responsible_department", "owner"}),
        ),
    )
    assert issued.required_permission == ComplianceReviewPermission.ISSUE_FINDING
    assert issued.target_lifecycle is FindingLifecycle.RECTIFYING


def test_generic_finding_service_accepts_observation_with_scenario_returned_permission() -> None:
    service, repository, lead, reviewer = _service()
    finding = service.create_finding(
        lead,
        repository.review_case.id,
        "Document retention interval should be clarified",
        FindingSeverity.LOW,
        {"criterion_reference": "7.5.3", "finding_type": "observation"},
        occurred_at=NOW,
    )

    with pytest.raises(ReviewAuthorizationError, match="accept_observation"):
        service.transition_finding(lead, finding.id, "accept_observation", occurred_at=NOW)

    accepted = service.transition_finding(
        reviewer,
        finding.id,
        "accept_observation",
        occurred_at=NOW,
    )

    assert accepted.lifecycle is FindingLifecycle.CLOSED
    transition_activity = repository.activities[-1]
    assert transition_activity.event_type == "finding.transitioned"
    assert transition_activity.metadata == {
        "action": "accept_observation",
        "from_lifecycle": "open",
        "to_lifecycle": "closed",
    }


def test_same_generic_transition_surface_dispatches_both_exact_scenarios() -> None:
    compliance_service, compliance_repository, compliance_lead, compliance_reviewer = _service()
    compliance_finding = compliance_service.create_finding(
        compliance_lead,
        compliance_repository.review_case.id,
        "Compliance observation",
        FindingSeverity.LOW,
        {"criterion_reference": "7.5.3", "finding_type": "observation"},
        occurred_at=NOW,
    )
    compliance_result = compliance_service.transition_finding(
        compliance_reviewer,
        compliance_finding.id,
        "accept_observation",
        occurred_at=NOW,
    )
    assert compliance_result.lifecycle is FindingLifecycle.CLOSED

    organization_id = OrganizationId(uuid4())
    process_lead = _user(organization_id)
    process_reviewer = _user(organization_id)
    process_case = ReviewCase(
        id=ReviewCaseId(uuid4()),
        organization_id=organization_id,
        plan_id=None,
        scenario_key=ScenarioKey("process_review"),
        scenario_version=ScenarioVersion(1),
        title="Process review comparison",
        lifecycle=ReviewCaseLifecycle.IN_PROGRESS,
        created_by=process_lead.id,
        created_at=NOW,
        scenario_data={"area_code": "LINE-A", "review_type": "routine"},
    )
    process_repository = Repository(process_case, process_lead, process_reviewer)
    process_service = _finding_service(process_repository)
    process_finding = process_service.create_finding(
        process_lead,
        process_case.id,
        "Process review finding",
        FindingSeverity.LOW,
        {"issue_type": "control_gap", "project_category": "assembly"},
        occurred_at=NOW,
    )

    with pytest.raises(ValueError, match="Unknown Finding action"):
        process_service.transition_finding(
            process_lead,
            process_finding.id,
            "accept_observation",
            occurred_at=NOW,
        )
