from sqlalchemy.orm import Session

from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.application.review_planning import ReviewPlanningService
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry
from easyaudit_next.review_core.persistence.repositories import (
    SqlAlchemyReviewCoreRepository,
    SqlAlchemyScenarioCatalogRepository,
)
from easyaudit_next.scenarios.process_review import PROCESS_REVIEW_V1


def build_scenario_registry() -> ScenarioRegistry:
    """Composition root for code-defined immutable Scenario policies."""

    registry = ScenarioRegistry()
    registry.register(PROCESS_REVIEW_V1)
    return registry


def build_review_planning_service(session: Session) -> ReviewPlanningService:
    """Wire generic Review Core application services to registered Scenario policies."""

    return ReviewPlanningService(
        SqlAlchemyReviewCoreRepository(session),
        SqlAlchemyScenarioCatalogRepository(session),
        SqlAlchemyUserRepository(session),
        build_scenario_registry(),
    )
