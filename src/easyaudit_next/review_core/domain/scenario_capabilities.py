from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from easyaudit_next.review_core.domain.models import (
    ActionItemLifecycle,
    AssignmentRole,
    FindingLifecycle,
    ReviewCaseLifecycle,
    SubmissionPurpose,
)


class WorkflowTransitionError(ValueError):
    """Raised when a Scenario workflow rejects a requested lifecycle transition."""


@dataclass(frozen=True, slots=True)
class ReviewCaseTransitionContext:
    reason: str | None = None
    all_findings_terminal: bool = False


@dataclass(frozen=True, slots=True)
class FindingTransitionContext:
    reason: str | None = None
    non_cancelled_action_count: int = 0
    all_non_cancelled_actions_done: bool = False


@dataclass(frozen=True, slots=True)
class ActionItemTransitionContext:
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    """Business relationships for one authenticated user; platform role is deliberately absent."""

    case_role_keys: frozenset[str] = field(default_factory=frozenset)
    explicit_finding_role_keys: frozenset[str] = field(default_factory=frozenset)
    department_finding_role_keys: frozenset[str] = field(default_factory=frozenset)
    action_assignment_roles: frozenset[AssignmentRole] = field(default_factory=frozenset)


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


class ActionItemWorkflowPolicy(Protocol):
    def transition(
        self,
        lifecycle: ActionItemLifecycle,
        action: str,
        context: ActionItemTransitionContext,
    ) -> ActionItemLifecycle: ...


class AuthorizationPolicy(Protocol):
    def allows(self, permission: str, context: AuthorizationContext) -> bool: ...


class SubmissionPolicy(Protocol):
    def validate_submission(
        self,
        purpose: SubmissionPurpose,
        payload: Mapping[str, object],
    ) -> tuple[str, ...]: ...
