from dataclasses import dataclass
from enum import StrEnum


class ReviewPlanningPermission(StrEnum):
    CREATE_REVIEW_PLAN = "create_review_plan"


@dataclass(frozen=True, slots=True)
class PlanningAuthorizationContext:
    """Pre-object organization facts for generic ReviewPlan authorization."""

    is_active_organization_user: bool = False


@dataclass(frozen=True, slots=True)
class CoreReviewPlanningAuthorizationPolicy:
    """ReviewPlan is a cross-Scenario Core container, so its creation is Core-owned."""

    def allows(
        self,
        permission: str,
        context: PlanningAuthorizationContext,
    ) -> bool:
        try:
            requested = ReviewPlanningPermission(permission)
        except ValueError:
            return False

        if requested is ReviewPlanningPermission.CREATE_REVIEW_PLAN:
            return context.is_active_organization_user
        return False


CORE_REVIEW_PLANNING_AUTHORIZATION = CoreReviewPlanningAuthorizationPolicy()
