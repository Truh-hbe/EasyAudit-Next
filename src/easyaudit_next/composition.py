from sqlalchemy.orm import Session

from easyaudit_next.application.case_team_coordination import CaseTeamUserCoordinator
from easyaudit_next.collaboration.automatic_reminder import AutomaticReminderEvaluator
from easyaudit_next.collaboration.notification_orchestration import NotificationOrchestrator
from easyaudit_next.collaboration.nudge import ManualNudgeService
from easyaudit_next.collaboration.reminder_sweep import AutomaticReminderSweep
from easyaudit_next.management.query_service import ManagementQueryService
from easyaudit_next.notifications.persistence import SqlAlchemyNotificationRepository
from easyaudit_next.notifications.service import NotificationService
from easyaudit_next.platform.application.administration import PlatformAdministrationService
from easyaudit_next.platform.application.authentication import AuthenticationService
from easyaudit_next.platform.application.services import IdentityOrganizationService
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyAuthSessionRepository,
    SqlAlchemyDepartmentRepository,
    SqlAlchemyLocalCredentialRepository,
    SqlAlchemyOrganizationRepository,
    SqlAlchemyPlatformAuditRepository,
    SqlAlchemyUserRepository,
)
from easyaudit_next.review_case_queries.context_service import ReviewCaseContextQueryService
from easyaudit_next.review_case_queries.query_service import ReviewCaseCollectionQueryService
from easyaudit_next.review_case_queries.review_catalog import ReviewCatalogQueryService
from easyaudit_next.review_core.application.create_idempotency import CreateIdempotencyService
from easyaudit_next.review_core.application.review_closure_findings import (
    ClosureAwareFindingLifecycleService,
)
from easyaudit_next.review_core.application.review_rectification import RectificationService
from easyaudit_next.review_core.application.review_verification import (
    ClosureAwareReviewPlanningService,
    VerificationClosureService,
)
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry
from easyaudit_next.review_core.persistence.idempotency_repository import (
    SqlAlchemyCreateIdempotencyRepository,
)
from easyaudit_next.review_core.persistence.rectification_repositories import (
    SqlAlchemyRectificationRepository,
)
from easyaudit_next.review_core.persistence.repositories import (
    SqlAlchemyScenarioCatalogRepository,
)
from easyaudit_next.review_core.persistence.verification_repositories import (
    SqlAlchemyVerificationClosureRepository,
)
from easyaudit_next.review_resource_queries.context_service import (
    ReviewResourceContextQueryService,
)
from easyaudit_next.scenarios.compliance_review import COMPLIANCE_REVIEW_V1
from easyaudit_next.scenarios.process_review import PROCESS_REVIEW_V1
from easyaudit_next.workbench.query_service import WorkbenchQueryService


def build_scenario_registry() -> ScenarioRegistry:
    """Composition root for code-defined immutable Scenario policies."""

    registry = ScenarioRegistry()
    registry.register(PROCESS_REVIEW_V1)
    registry.register(COMPLIANCE_REVIEW_V1)
    return registry


def build_review_planning_service(session: Session) -> ClosureAwareReviewPlanningService:
    """Wire planning with M2.5 Case-level closure coordination."""

    return ClosureAwareReviewPlanningService(
        SqlAlchemyVerificationClosureRepository(session),
        SqlAlchemyScenarioCatalogRepository(session),
        SqlAlchemyUserRepository(session),
        build_scenario_registry(),
    )


def build_platform_administration_service(session: Session) -> PlatformAdministrationService:
    """Wire the existing platform administration service at the composition boundary."""

    organizations = SqlAlchemyOrganizationRepository(session)
    departments = SqlAlchemyDepartmentRepository(session)
    users = SqlAlchemyUserRepository(session)
    credentials = SqlAlchemyLocalCredentialRepository(session)
    audit = SqlAlchemyPlatformAuditRepository(session)
    auth = AuthenticationService(
        credentials,
        SqlAlchemyAuthSessionRepository(session),
        users,
        audit,
    )
    return PlatformAdministrationService(
        IdentityOrganizationService(organizations, departments, users),
        organizations,
        departments,
        users,
        credentials,
        auth,
        audit,
    )


def build_create_idempotency_service(session: Session) -> CreateIdempotencyService:
    """Wire the ReviewPlan / ReviewCase creation idempotency claim."""

    return CreateIdempotencyService(SqlAlchemyCreateIdempotencyRepository(session))


def build_case_team_coordinator(session: Session) -> CaseTeamUserCoordinator:
    """Wire the shared Organization-rooted Case/User mutation coordinator."""

    return CaseTeamUserCoordinator(
        SqlAlchemyOrganizationRepository(session),
        SqlAlchemyVerificationClosureRepository(session),
        SqlAlchemyUserRepository(session),
        build_scenario_registry(),
        build_review_planning_service(session),
        build_platform_administration_service(session),
    )


def build_finding_lifecycle_service(session: Session) -> ClosureAwareFindingLifecycleService:
    """Wire Finding creation to the M2.5 Case-level aggregate guard."""

    return ClosureAwareFindingLifecycleService(
        SqlAlchemyVerificationClosureRepository(session),
        SqlAlchemyUserRepository(session),
        SqlAlchemyDepartmentRepository(session),
        build_scenario_registry(),
    )


def build_rectification_service(session: Session) -> RectificationService:
    """Wire generic rectification use cases to exact versioned Scenario capabilities."""

    return RectificationService(
        SqlAlchemyRectificationRepository(session),
        SqlAlchemyUserRepository(session),
        SqlAlchemyDepartmentRepository(session),
        build_scenario_registry(),
    )


def build_verification_closure_service(session: Session) -> VerificationClosureService:
    """Wire M2.5 verification/reopen to the shared parent-Case concurrency guard."""

    return VerificationClosureService(
        SqlAlchemyVerificationClosureRepository(session),
        build_scenario_registry(),
    )


def build_workbench_query_service(session: Session) -> WorkbenchQueryService:
    """Wire the M3.1 read side without expanding Review Core repositories."""

    return WorkbenchQueryService(session, build_scenario_registry())


def build_review_case_collection_query_service(
    session: Session,
) -> ReviewCaseCollectionQueryService:
    """Wire the M3.5.2 bounded Product collection outside Review Core repositories."""

    return ReviewCaseCollectionQueryService(session, build_scenario_registry())


def build_review_case_context_query_service(
    session: Session,
) -> ReviewCaseContextQueryService:
    """Wire Case-scoped presentation reads after canonical Case authorization."""

    return ReviewCaseContextQueryService(session, build_review_planning_service(session))


def build_review_catalog_query_service(session: Session) -> ReviewCatalogQueryService:
    """Wire the creatable Scenario projection without expanding Review Core."""

    return ReviewCatalogQueryService(
        SqlAlchemyScenarioCatalogRepository(session),
        build_scenario_registry(),
    )


def build_review_resource_context_query_service(
    session: Session,
) -> ReviewResourceContextQueryService:
    """Wire target-scoped Finding/Action presentation reads outside Review Core."""

    return ReviewResourceContextQueryService(
        session,
        build_finding_lifecycle_service(session),
        build_rectification_service(session),
        build_scenario_registry(),
    )


def build_management_query_service(session: Session) -> ManagementQueryService:
    """Wire the M3.3 management read side against exact Scenario policies."""

    return ManagementQueryService(session, build_scenario_registry())


def build_notification_service(session: Session) -> NotificationService:
    """Wire recipient-local Notification persistence and inbox operations."""

    return NotificationService(SqlAlchemyNotificationRepository(session))


def build_notification_orchestrator(session: Session) -> NotificationOrchestrator:
    """Wire M3.2 collaboration orchestration outside Review Core."""

    return NotificationOrchestrator(
        session,
        build_scenario_registry(),
        build_notification_service(session),
    )


def build_manual_nudge_service(session: Session) -> ManualNudgeService:
    """Wire M3.4 human nudge orchestration against exact Scenario recipient semantics."""

    return ManualNudgeService(
        session,
        build_scenario_registry(),
        build_notification_service(session),
    )


def build_automatic_reminder_evaluator(session: Session) -> AutomaticReminderEvaluator:
    """Wire one-occurrence M3.4 deadline evaluation without scheduler/cadence ownership."""

    return AutomaticReminderEvaluator(
        session,
        build_scenario_registry(),
        build_notification_service(session),
    )


def build_automatic_reminder_sweep(session: Session) -> AutomaticReminderSweep:
    """Wire one scheduler-neutral sweep; the caller still owns clock and cadence."""

    return AutomaticReminderSweep(session, build_automatic_reminder_evaluator(session))
