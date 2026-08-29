from dataclasses import dataclass

from easyaudit_next.platform.domain.models import User
from easyaudit_next.review_core.domain.models import ScenarioKey, ScenarioVersion
from easyaudit_next.review_core.domain.repositories import ScenarioCatalogRepository
from easyaudit_next.review_core.domain.scenario_capabilities import AuthorizationContext
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry


@dataclass(frozen=True, slots=True)
class ReviewCatalogItem:
    """The minimal, creatable Scenario projection exposed to Product."""

    scenario_key: ScenarioKey
    scenario_version: ScenarioVersion
    display_name: str


class ReviewCatalogQueryService:
    """Read the intersection of Organization publication and exact Case capability."""

    def __init__(
        self,
        scenario_catalog: ScenarioCatalogRepository,
        registry: ScenarioRegistry,
    ) -> None:
        self._scenario_catalog = scenario_catalog
        self._registry = registry

    def list_creatable(self, actor: User) -> tuple[ReviewCatalogItem, ...]:
        context = AuthorizationContext(is_active_organization_user=actor.is_active)
        items: list[ReviewCatalogItem] = []
        for scenario in self._scenario_catalog.list_for_organization(actor.organization_id):
            if not scenario.is_active:
                continue
            for publication in self._scenario_catalog.list_versions(
                actor.organization_id,
                scenario.id,
            ):
                try:
                    policy = self._registry.get(scenario.key, publication.version)
                except LookupError:
                    continue
                decision = policy.case_creation.decision()
                if not policy.authorization.allows(decision.required_permission, context):
                    continue
                items.append(
                    ReviewCatalogItem(
                        scenario_key=scenario.key,
                        scenario_version=publication.version,
                        display_name=policy.scenario.name,
                    )
                )
        return tuple(
            sorted(items, key=lambda item: (item.scenario_key, item.scenario_version))
        )
