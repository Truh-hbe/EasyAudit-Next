from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from easyaudit_next.review_core.domain.models import (
    ActionItemLifecycle,
    FindingLifecycle,
    ReviewCaseLifecycle,
    SubmissionPurpose,
)
from easyaudit_next.rules import RuleCode, RuleViolation


class WorkflowTransitionError(RuleViolation):
    """Raised when a Scenario workflow rejects a requested lifecycle transition."""


class SubmissionDecisionError(RuleViolation):
    """Raised when a formal Submission request is not valid for the Scenario."""


class FindingOperationError(RuleViolation):
    """Raised when Scenario-owned Finding operation invariants are not satisfied."""


class ActionItemOperationError(RuleViolation):
    """Raised when Scenario-owned ActionItem operation invariants are not satisfied."""


def invalid_transition(
    label: str, entity: str, lifecycle: StrEnum, action: StrEnum
) -> WorkflowTransitionError:
    """`label` is the English entity name for `detail`; `entity` is its stable snake_case key."""
    return WorkflowTransitionError(
        RuleCode.WORKFLOW_INVALID_TRANSITION,
        f"{label} cannot perform {action.value!r} from lifecycle {lifecycle.value!r}",
        params={"entity": entity, "action": action.value, "lifecycle": lifecycle.value},
    )


class ActorKind(StrEnum):
    USER = "user"
    DEPARTMENT = "department"


class PermissionSource(StrEnum):
    DIRECT = "direct"
    DEPARTMENT_MEMBERSHIP = "department_membership"


class CollaborationRecipientIntent(StrEnum):
    """Versioned collaboration responsibility semantics owned by a Scenario."""

    FINDING_RECTIFICATION = "finding_rectification"
    ACTION_EXECUTION = "action_execution"
    CASE_DEADLINE = "case_deadline"


@dataclass(frozen=True, slots=True)
class RoleSpecification:
    """Versioned rules for one Scenario relationship role."""

    key: str
    allowed_actor_kinds: frozenset[ActorKind]
    permission_sources: frozenset[PermissionSource]

    def __post_init__(self) -> None:
        if not self.key.strip() or self.key != self.key.strip():
            raise ValueError("Role key must not be blank or padded")
        if not self.allowed_actor_kinds:
            raise ValueError("RoleSpecification requires at least one actor kind")
        if not self.permission_sources:
            raise ValueError("RoleSpecification requires at least one permission source")

    def accepts_grant(self, grant: RoleGrant) -> bool:
        return (
            grant.role_key == self.key
            and grant.actor_kind in self.allowed_actor_kinds
            and grant.source in self.permission_sources
        )


@dataclass(frozen=True, slots=True)
class RoleGrant:
    """One relationship through which the current user derives Scenario authority."""

    role_key: str
    actor_kind: ActorKind
    source: PermissionSource


@dataclass(frozen=True, slots=True)
class ReviewCaseTransitionContext:
    reason: str | None = None
    all_findings_terminal: bool = False


@dataclass(frozen=True, slots=True)
class FindingTransitionContext:
    reason: str | None = None
    non_cancelled_action_count: int = 0
    all_non_cancelled_actions_done: bool = False
    scenario_data: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FindingOperationContext:
    """Scenario-neutral facts needed to validate Finding operations."""

    case_lifecycle: ReviewCaseLifecycle
    current_finding_lifecycle: FindingLifecycle | None = None
    scenario_data: Mapping[str, object] = field(default_factory=dict)
    participant_role_keys: frozenset[str] = field(default_factory=frozenset)
    non_cancelled_action_count: int = 0
    all_non_cancelled_actions_done: bool = False
    reason: str | None = None

    def has_participant_role(self, role_key: str) -> bool:
        return role_key in self.participant_role_keys


@dataclass(frozen=True, slots=True)
class DirectFindingTransitionDecision:
    """Scenario-owned direct Finding transition intent for generic persistence."""

    required_permission: str
    target_lifecycle: FindingLifecycle


@dataclass(frozen=True, slots=True)
class ActionItemOperationContext:
    """Scenario-neutral facts needed to validate rectification operations."""

    case_lifecycle: ReviewCaseLifecycle
    finding_lifecycle: FindingLifecycle
    current_action_lifecycle: ActionItemLifecycle | None = None
    assignee_role_keys: frozenset[str] = field(default_factory=frozenset)
    # Any User executor (primary or collaborator) that is still an active User.
    has_active_assignee: bool = False
    reason: str | None = None

    def has_assignee_role(self, role_key: str) -> bool:
        return role_key in self.assignee_role_keys


@dataclass(frozen=True, slots=True)
class ActionItemTransitionContext:
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    """Business facts for one user; platform administrator status is deliberately absent."""

    is_active_organization_user: bool = False
    case_role_grants: frozenset[RoleGrant] = field(default_factory=frozenset)
    finding_role_grants: frozenset[RoleGrant] = field(default_factory=frozenset)
    action_role_grants: frozenset[RoleGrant] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class CaseCreationDecision:
    """Scenario-owned behavior that must be applied atomically when a Case is created."""

    required_permission: str
    initial_lifecycle: ReviewCaseLifecycle
    creator_role_keys: tuple[str, ...]
    activity_event_type: str
    requires_atomic_membership: bool = True


@dataclass(frozen=True, slots=True)
class SubmissionRequest:
    """Formal Finding submission plus the workflow facts needed to decide it."""

    current_lifecycle: FindingLifecycle
    action: str
    purpose: SubmissionPurpose
    payload: Mapping[str, object]
    transition_context: FindingTransitionContext = field(
        default_factory=FindingTransitionContext
    )


@dataclass(frozen=True, slots=True)
class SubmissionDecision:
    """One atomic Submission + Finding lifecycle + Activity write intent."""

    required_permission: str
    target_lifecycle: FindingLifecycle
    activity_event_type: str
    requires_atomic_write: bool = True


class ReviewCaseWorkflowPolicy(Protocol):
    def transition(
        self,
        lifecycle: ReviewCaseLifecycle,
        action: str,
        context: ReviewCaseTransitionContext,
    ) -> ReviewCaseLifecycle: ...


class FindingWorkflowPolicy(Protocol):
    def transition(
        self,
        lifecycle: FindingLifecycle,
        action: str,
        context: FindingTransitionContext,
    ) -> FindingLifecycle: ...


class FindingOperationPolicy(Protocol):
    def validate_create(self, context: FindingOperationContext) -> None: ...

    def validate_participant_management(
        self,
        context: FindingOperationContext,
    ) -> None: ...

    def validate_transition(
        self,
        action: str,
        context: FindingOperationContext,
    ) -> None: ...


class DirectFindingTransitionPolicy(Protocol):
    def decide(
        self,
        action: str,
        context: FindingOperationContext,
    ) -> DirectFindingTransitionDecision: ...


class ActionItemWorkflowPolicy(Protocol):
    def transition(
        self,
        lifecycle: ActionItemLifecycle,
        action: str,
        context: ActionItemTransitionContext,
    ) -> ActionItemLifecycle: ...


class ActionItemOperationPolicy(Protocol):
    def validate_create(self, context: ActionItemOperationContext) -> None: ...

    def validate_assignee_management(
        self,
        context: ActionItemOperationContext,
    ) -> None: ...

    def validate_transition(
        self,
        action: str,
        context: ActionItemOperationContext,
    ) -> None: ...

    def validate_evidence_registration(
        self,
        context: ActionItemOperationContext,
    ) -> None: ...

    def validate_transfer_and_reopen_state(self, context: ActionItemOperationContext) -> None:
        """State preconditions of transfer-and-reopen (no reason needed): shared by the
        command and the candidate search."""
        ...

    def decide_transfer_and_reopen(self, context: ActionItemOperationContext) -> str:
        """Validate the atomic transfer-and-reopen command (state and reason) and return the
        workflow action that reopens the ActionItem (the target state comes from
        `action_workflow`)."""
        ...


class ReviewCaseCreationPolicy(Protocol):
    def decision(self) -> CaseCreationDecision: ...


class AuthorizationPolicy(Protocol):
    def allows(self, permission: str, context: AuthorizationContext) -> bool: ...


class CollaborationRecipientPolicy(Protocol):
    """Scenario-owned answer to who should receive a collaboration intent."""

    def is_recipient(
        self,
        intent: CollaborationRecipientIntent,
        context: AuthorizationContext,
    ) -> bool: ...


class SubmissionPolicy(Protocol):
    def decide(self, request: SubmissionRequest) -> SubmissionDecision: ...
