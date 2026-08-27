from sqlalchemy.orm import Session

from easyaudit_next.collaboration.notification_orchestration import NotificationOrchestrator
from easyaudit_next.notifications.persistence import SqlAlchemyNotificationRepository
from easyaudit_next.notifications.service import NotificationService
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyDepartmentRepository,
    SqlAlchemyUserRepository,
)
from easyaudit_next.review_core.application.review_closure_findings import (
    ClosureAwareFindingLifecycleService,
)
from easyaudit_next.review_core.application.review_rectification import RectificationService
from easyaudit_next.review_core.application.review_verification import (
    ClosureAwareReviewPlanningService,
    VerificationClosureService,
)
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry
from easyaudit_next.review_core.persistence.rectification_repositories import (
    SqlAlchemyRectificationRepository,
)
from easyaudit_next.review_core.persistence.repositories import (
    SqlAlchemyScenarioCatalogRepository,
)
from easyaudit_next.review_core.persistence.verification_repositories import (
    SqlAlchemyVerificationClosureRepository,
)
from easyaudit_next.scenarios.process_review import PROCESS_REVIEW_V1
from easyaudit_next.workbench.query_service import WorkbenchQueryService


def build_scenario_registry() -> ScenarioRegistry:
    """Composition root for code-defined immutable Scenario policies."""

    registry = ScenarioRegistry()
    registry.register(PROCESS_REVIEW_V1)
    return registry


def build_review_planning_service(session: Session) -> ClosureAwareReviewPlanningService:
    """Wire planning with M2.5 Case-level closure coordination."""

    return ClosureAwareReviewPlanningService(
        SqlAlchemyVerificationClosureRepository(session),
        SqlAlchemyScenarioCatalogRepository(session),
        SqlAlchemyUserRepository(session),
        build_scenario_registry(),
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
