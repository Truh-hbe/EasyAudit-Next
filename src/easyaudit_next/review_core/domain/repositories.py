from typing import Protocol

from easyaudit_next.platform.domain.ids import OrganizationId
from easyaudit_next.review_core.domain.ids import ScenarioDefinitionId
from easyaudit_next.review_core.domain.models import (
    ScenarioDefinition,
    ScenarioKey,
    ScenarioVersion,
    ScenarioVersionPublication,
)


class ScenarioCatalogRepository(Protocol):
    def add_scenario(self, scenario: ScenarioDefinition) -> None: ...

    def add_version(self, publication: ScenarioVersionPublication) -> None: ...

    def get_by_key(
        self,
        organization_id: OrganizationId,
        key: ScenarioKey,
    ) -> ScenarioDefinition | None: ...

    def get_version(
        self,
        scenario_id: ScenarioDefinitionId,
        version: ScenarioVersion,
    ) -> ScenarioVersionPublication | None: ...
