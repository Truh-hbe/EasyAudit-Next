from datetime import UTC, datetime
from uuid import uuid4

from easyaudit_next.platform.domain.ids import OrganizationId
from easyaudit_next.review_core.domain.ids import ScenarioDefinitionId, ScenarioVersionId
from easyaudit_next.review_core.domain.models import (
    ScenarioDefinition,
    ScenarioKey,
    ScenarioVersion,
    ScenarioVersionPublication,
)
from easyaudit_next.review_core.domain.repositories import ScenarioCatalogRepository
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry


class ScenarioVersionAlreadyPublishedError(ValueError):
    """The organization already published this exact Scenario version."""


class ScenarioCatalogService:
    """Publishes code-known policies into an organization's durable catalog."""

    def __init__(
        self,
        repository: ScenarioCatalogRepository,
        registry: ScenarioRegistry,
    ) -> None:
        self._repository = repository
        self._registry = registry

    def publish(
        self,
        organization_id: OrganizationId,
        key: ScenarioKey,
        version: ScenarioVersion,
        *,
        published_at: datetime | None = None,
    ) -> tuple[ScenarioDefinition, ScenarioVersionPublication]:
        policy = self._registry.get(key, version)
        scenario = self._repository.get_by_key(organization_id, key)
        if scenario is None:
            scenario = ScenarioDefinition(
                id=ScenarioDefinitionId(uuid4()),
                organization_id=organization_id,
                key=key,
                name=policy.scenario.name,
                is_active=policy.scenario.enabled,
            )
            self._repository.add_scenario(scenario)

        if self._repository.get_version(scenario.id, version) is not None:
            raise ScenarioVersionAlreadyPublishedError(
                f"Scenario version is already published: {key}@{version}"
            )

        publication = ScenarioVersionPublication(
            id=ScenarioVersionId(uuid4()),
            scenario_id=scenario.id,
            organization_id=organization_id,
            version=version,
            published_at=published_at or datetime.now(UTC),
        )
        self._repository.add_version(publication)
        return scenario, publication
