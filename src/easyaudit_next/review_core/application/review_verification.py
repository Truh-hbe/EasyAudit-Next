from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from easyaudit_next.platform.domain.models import User
from easyaudit_next.platform.domain.repositories import UserRepository
from easyaudit_next.review_core.application.authorization import (
    build_rectification_authorization_context,
    lock_case_and_build_context,
)
from easyaudit_next.review_core.application.review_findings import (
    ConcurrentFindingTransitionError,
)
from easyaudit_next.review_core.application.review_planning import (
    ConcurrentCaseTransitionError,
    ReviewAuthorizationError,
)
from easyaudit_next.review_core.application.review_rectification import (
    ActionAwareReviewPlanningService,
)
from easyaudit_next.review_core.domain.ids import (
    ActivityId,
    FindingId,
    ReviewCaseId,
    SubmissionId,
)
from easyaudit_next.review_core.domain.models import (
    Activity,
    Finding,
    FindingActivitySubject,
    FindingLifecycle,
    ReviewCase,
    ReviewCaseActivitySubject,
    ReviewCaseLifecycle,
    Submission,
    SubmissionActivitySubject,
    SubmissionPurpose,
)
from easyaudit_next.review_core.domain.repositories import ScenarioCatalogRepository
from easyaudit_next.review_core.domain.scenario_capabilities import (
    AuthorizationContext,
    FindingOperationContext,
    FindingTransitionContext,
    ReviewCaseTransitionContext,
    SubmissionRequest,
)
from easyaudit_next.review_core.domain.scenario_registry import ScenarioPolicy, ScenarioRegistry
from easyaudit_next.review_core.domain.verification_repositories import (
    VerificationClosureRepository,
)

VIEW_FINDING_PERMISSION = "view_finding"
REOPEN_FINDING_PERMISSION = "reopen_finding"
TRANSITION_CASE_PERMISSION = "transition_case"


class ClosureAwareReviewPlanningService(ActionAwareReviewPlanningService):
    """M2.2/M2.4 planning behavior with the M2.5 Case aggregate guard."""

    def __init__(
        self,
        repository: VerificationClosureRepository,
        scenario_catalog: ScenarioCatalogRepository,
        users: UserRepository,
        registry: ScenarioRegistry,
    ) -> None:
        super().__init__(repository, scenario_catalog, users, registry)
        self._closure_repository = repository

    def transition_case(
        self,
        actor: User,
        case_id: ReviewCaseId,
        action: str,
        *,
        reason: str | None = None,
        occurred_at: datetime | None = None,
    ) -> ReviewCase:
        review_case, policy, context = self._case_context(actor, case_id)
        if not policy.authorization.allows(TRANSITION_CASE_PERMISSION, context):
            raise ReviewAuthorizationError("lead role required to transition ReviewCase")

        locked_case, context = lock_case_and_build_context(
            self._closure_repository,
            actor,
            review_case.id,
        )
        if not policy.authorization.allows(TRANSITION_CASE_PERMISSION, context):
            raise ReviewAuthorizationError("lead role required to transition ReviewCase")
        if locked_case.lifecycle is not review_case.lifecycle:
            raise ConcurrentCaseTransitionError("Concurrent ReviewCase transition")

        findings = self._closure_repository.list_findings_for_closure(
            actor.organization_id,
            locked_case.id,
        )
        all_findings_terminal = all(
            finding.lifecycle in {FindingLifecycle.CLOSED, FindingLifecycle.VOIDED}
            for finding in findings
        )
        target = policy.case_workflow.transition(
            locked_case.lifecycle,
            action,
            ReviewCaseTransitionContext(
                reason=reason,
                all_findings_terminal=all_findings_terminal,
            ),
        )
        now = occurred_at or datetime.now(UTC)
        updated = replace(
            locked_case,
            lifecycle=target,
            started_at=(
                now
                if target is ReviewCaseLifecycle.IN_PROGRESS and locked_case.started_at is None
                else locked_case.started_at
            ),
            fieldwork_completed_at=(
                now
                if target is ReviewCaseLifecycle.AWAITING_CLOSURE
                else locked_case.fieldwork_completed_at
            ),
            closed_at=(now if target is ReviewCaseLifecycle.CLOSED else locked_case.closed_at),
        )
        if not self._closure_repository.update_case(
            updated,
            expected_lifecycle=locked_case.lifecycle,
        ):
            raise ConcurrentCaseTransitionError("Concurrent ReviewCase transition")

        metadata: dict[str, object] = {
            "action": action,
            "from_lifecycle": locked_case.lifecycle.value,
            "to_lifecycle": target.value,
        }
        if reason is not None:
            metadata["reason"] = reason
        self._closure_repository.add_activity(
            Activity(
                id=ActivityId(uuid4()),
                organization_id=actor.organization_id,
                subject=ReviewCaseActivitySubject(locked_case.id),
                event_type="review_case.transitioned",
                actor_id=actor.id,
                occurred_at=now,
                metadata=metadata,
            )
        )
        return updated


class VerificationClosureService:
    """Scenario-neutral M2.5 verification, reopen, and closure coordination."""

    def __init__(
        self,
        repository: VerificationClosureRepository,
        registry: ScenarioRegistry,
    ) -> None:
        self._repository = repository
        self._registry = registry

    def submit_verification(
        self,
        actor: User,
        finding_id: FindingId,
        action: str,
        payload: dict[str, object],
        *,
        occurred_at: datetime | None = None,
    ) -> tuple[Submission, Finding]:
        finding, review_case, policy, context = self._finding_context(actor, finding_id)
        if not policy.authorization.allows(VIEW_FINDING_PERMISSION, context):
            raise ReviewAuthorizationError("Finding is not visible to this user")

        locked_case, context = self._lock_expected_case(actor, review_case, finding, policy)
        if locked_case.lifecycle is ReviewCaseLifecycle.CLOSED:
            raise ValueError("Closed ReviewCase cannot accept Finding verification")
        finding = self._lock_expected_finding(actor, finding)

        decision = policy.submission_policy.decide(
            SubmissionRequest(
                current_lifecycle=finding.lifecycle,
                action=action,
                purpose=SubmissionPurpose.VERIFICATION,
                payload=dict(payload),
                transition_context=FindingTransitionContext(),
            )
        )
        if not policy.authorization.allows(decision.required_permission, context):
            raise ReviewAuthorizationError("reviewer role required to verify Finding")

        updated = replace(finding, lifecycle=decision.target_lifecycle)
        if not self._repository.update_finding(
            updated,
            expected_lifecycle=finding.lifecycle,
        ):
            raise ConcurrentFindingTransitionError("Concurrent Finding transition")

        now = occurred_at or datetime.now(UTC)
        submission = Submission(
            id=SubmissionId(uuid4()),
            organization_id=actor.organization_id,
            case_id=locked_case.id,
            finding_id=finding.id,
            purpose=SubmissionPurpose.VERIFICATION,
            submitted_by=actor.id,
            submitted_at=now,
            payload=dict(payload),
        )
        self._repository.add_submission(submission)
        self._repository.add_activity(
            Activity(
                id=ActivityId(uuid4()),
                organization_id=actor.organization_id,
                subject=SubmissionActivitySubject(submission.id),
                event_type=decision.activity_event_type,
                actor_id=actor.id,
                occurred_at=now,
                metadata={
                    "action": action,
                    "finding_id": str(finding.id),
                    "from_lifecycle": finding.lifecycle.value,
                    "to_lifecycle": updated.lifecycle.value,
                },
            )
        )
        return submission, updated

    def reopen_finding(
        self,
        actor: User,
        finding_id: FindingId,
        *,
        reason: str,
        occurred_at: datetime | None = None,
    ) -> Finding:
        finding, review_case, policy, context = self._finding_context(actor, finding_id)
        if not policy.authorization.allows(VIEW_FINDING_PERMISSION, context):
            raise ReviewAuthorizationError("Finding is not visible to this user")
        if not policy.authorization.allows(REOPEN_FINDING_PERMISSION, context):
            raise ReviewAuthorizationError(
                "lead, auditor, or reviewer role required to reopen Finding"
            )

        locked_case, context = self._lock_expected_case(actor, review_case, finding, policy)
        if not policy.authorization.allows(REOPEN_FINDING_PERMISSION, context):
            raise ReviewAuthorizationError(
                "lead, auditor, or reviewer role required to reopen Finding"
            )
        if locked_case.lifecycle is ReviewCaseLifecycle.CLOSED:
            raise ValueError("Finding cannot be reopened after ReviewCase closure")
        finding = self._lock_expected_finding(actor, finding)

        operation_context = FindingOperationContext(
            case_lifecycle=locked_case.lifecycle,
            current_finding_lifecycle=finding.lifecycle,
            reason=reason,
        )
        policy.finding_operations.validate_transition("reopen", operation_context)
        target = policy.finding_workflow.transition(
            finding.lifecycle,
            "reopen",
            FindingTransitionContext(reason=reason),
        )
        updated = replace(finding, lifecycle=target)
        if not self._repository.update_finding(
            updated,
            expected_lifecycle=finding.lifecycle,
        ):
            raise ConcurrentFindingTransitionError("Concurrent Finding transition")

        now = occurred_at or datetime.now(UTC)
        self._repository.add_activity(
            Activity(
                id=ActivityId(uuid4()),
                organization_id=actor.organization_id,
                subject=FindingActivitySubject(finding.id),
                event_type="finding.reopened",
                actor_id=actor.id,
                occurred_at=now,
                metadata={
                    "action": "reopen",
                    "reason": reason,
                    "from_lifecycle": finding.lifecycle.value,
                    "to_lifecycle": updated.lifecycle.value,
                },
            )
        )
        return updated

    def _finding_context(
        self,
        actor: User,
        finding_id: FindingId,
    ) -> tuple[Finding, ReviewCase, ScenarioPolicy, AuthorizationContext]:
        self._require_active(actor)
        finding = self._repository.get_finding(actor.organization_id, finding_id)
        if finding is None:
            raise LookupError("Finding not found")
        review_case = self._repository.get_case(actor.organization_id, finding.case_id)
        if review_case is None:
            raise LookupError("ReviewCase not found")
        policy = self._registry.get(review_case.scenario_key, review_case.scenario_version)
        context = build_rectification_authorization_context(
            self._repository,
            actor,
            review_case.id,
            finding_id=finding.id,
        )
        return finding, review_case, policy, context

    def _lock_expected_case(
        self,
        actor: User,
        expected: ReviewCase,
        finding: Finding,
        policy: ScenarioPolicy,
    ) -> tuple[ReviewCase, AuthorizationContext]:
        """Case lock first, then authorize on post-lock grants, then check the lifecycle."""
        locked, context = lock_case_and_build_context(
            self._repository,
            actor,
            expected.id,
            finding_id=finding.id,
        )
        if not policy.authorization.allows(VIEW_FINDING_PERMISSION, context):
            raise ReviewAuthorizationError("Finding is not visible to this user")
        if locked.lifecycle is not expected.lifecycle:
            raise ConcurrentCaseTransitionError("Concurrent ReviewCase transition")
        return locked, context

    def _lock_expected_finding(self, actor: User, expected: Finding) -> Finding:
        locked = self._repository.lock_finding_for_verification(
            actor.organization_id,
            expected.id,
        )
        if locked is None:
            raise LookupError("Finding not found")
        if locked.lifecycle is not expected.lifecycle:
            raise ConcurrentFindingTransitionError("Concurrent Finding transition")
        return locked

    @staticmethod
    def _require_active(actor: User) -> None:
        if not actor.is_active:
            raise ReviewAuthorizationError("Active organization user required")
