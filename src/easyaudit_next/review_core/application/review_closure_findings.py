from datetime import UTC, datetime
from uuid import uuid4

from easyaudit_next.platform.domain.models import User
from easyaudit_next.platform.domain.repositories import DepartmentRepository, UserRepository
from easyaudit_next.review_core.application.authorization import (
    build_rectification_authorization_context,
    lock_case_and_build_context,
)
from easyaudit_next.review_core.application.review_planning import (
    ReviewAuthorizationError,
)
from easyaudit_next.review_core.application.review_rectification import (
    ActionAwareFindingLifecycleService,
)
from easyaudit_next.review_core.domain.ids import ActivityId, FindingId, ReviewCaseId
from easyaudit_next.review_core.domain.models import (
    Activity,
    Finding,
    FindingActivitySubject,
    FindingLifecycle,
    FindingSeverity,
    ReviewCase,
)
from easyaudit_next.review_core.domain.scenario_capabilities import (
    AuthorizationContext,
    FindingOperationContext,
)
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry
from easyaudit_next.review_core.domain.verification_repositories import (
    VerificationClosureRepository,
)

CREATE_FINDING_PERMISSION = "create_finding"


class ClosureAwareFindingLifecycleService(ActionAwareFindingLifecycleService):
    """M2.3 Finding use cases with the M2.5 parent-Case creation cutover."""

    def __init__(
        self,
        repository: VerificationClosureRepository,
        users: UserRepository,
        departments: DepartmentRepository,
        registry: ScenarioRegistry,
    ) -> None:
        super().__init__(repository, users, departments, registry)
        self._closure_repository = repository

    def create_finding(
        self,
        actor: User,
        case_id: ReviewCaseId,
        title: str,
        severity: FindingSeverity,
        scenario_data: dict[str, object],
        *,
        description: str | None = None,
        occurred_at: datetime | None = None,
    ) -> Finding:
        review_case, policy = self._case_policy(actor, case_id)
        context = build_rectification_authorization_context(
            self._closure_repository,
            actor,
            review_case.id,
        )

        def authorize(_case: ReviewCase, current: AuthorizationContext) -> None:
            if not policy.authorization.allows(CREATE_FINDING_PERMISSION, current):
                raise ReviewAuthorizationError("lead or auditor role required to create Finding")

        authorize(review_case, context)
        locked_case, _, _ = lock_case_and_build_context(
            self._closure_repository,
            self._users,
            actor,
            review_case,
            lambda fresh: build_rectification_authorization_context(
                self._closure_repository,
                fresh,
                review_case.id,
            ),
            authorize,
        )

        policy.finding_operations.validate_create(
            FindingOperationContext(case_lifecycle=locked_case.lifecycle)
        )
        self._validate_title(title)
        errors = policy.validate_finding_input(scenario_data)
        if errors:
            raise ValueError("; ".join(errors))

        now = occurred_at or datetime.now(UTC)
        finding = Finding(
            id=FindingId(uuid4()),
            organization_id=actor.organization_id,
            case_id=locked_case.id,
            title=title,
            description=description,
            severity=severity,
            lifecycle=FindingLifecycle.OPEN,
            raised_by=actor.id,
            raised_at=now,
            scenario_data=dict(scenario_data),
        )
        self._closure_repository.add_finding(finding)
        self._closure_repository.add_activity(
            Activity(
                id=ActivityId(uuid4()),
                organization_id=actor.organization_id,
                subject=FindingActivitySubject(finding.id),
                event_type="finding.created",
                actor_id=actor.id,
                occurred_at=now,
                metadata={"case_id": str(locked_case.id)},
            )
        )
        return finding
