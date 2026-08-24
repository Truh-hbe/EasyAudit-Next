from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from easyaudit_next.platform.domain.ids import OrganizationId
from easyaudit_next.review_core.application.scenario_catalog import (
    ScenarioCatalogService,
    ScenarioVersionAlreadyPublishedError,
)
from easyaudit_next.review_core.domain.ids import ScenarioDefinitionId
from easyaudit_next.review_core.domain.models import (
    Scenario,
    ScenarioDefinition,
    ScenarioKey,
    ScenarioVersion,
    ScenarioVersionPublication,
)
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry


@dataclass(frozen=True)
class Policy:
    scenario: Scenario
    case_role_keys: tuple[str, ...] = ("lead",)
    finding_participant_role_keys: tuple[str, ...] = ("owner",)

    def validate_case_input(self, payload: Mapping[str, object]) -> tuple[str, ...]:
        return ()


class FakeScenarioCatalogRepository:
    def __init__(self) -> None:
        self.scenarios: dict[tuple[OrganizationId, ScenarioKey], ScenarioDefinition] = {}
        self.versions: dict[
            tuple[OrganizationId, ScenarioDefinitionId, ScenarioVersion],
            ScenarioVersionPublication,
        ] = {}

    def add_scenario(self, scenario: ScenarioDefinition) -> None:
        self.scenarios[(scenario.organization_id, scenario.key)] = scenario

    def add_version(self, publication: ScenarioVersionPublication) -> None:
        self.versions[
            (publication.organization_id, publication.scenario_id, publication.version)
        ] = publication

    def get_by_key(
        self,
        organization_id: OrganizationId,
        key: ScenarioKey,
    ) -> ScenarioDefinition | None:
        return self.scenarios.get((organization_id, key))

    def get_version(
        self,
        organization_id: OrganizationId,
        scenario_id: ScenarioDefinitionId,
        version: ScenarioVersion,
    ) -> ScenarioVersionPublication | None:
        return self.versions.get((organization_id, scenario_id, version))

    def list_for_organization(
        self, organization_id: OrganizationId
    ) -> tuple[ScenarioDefinition, ...]:
        return tuple(
            scenario
            for scenario in self.scenarios.values()
            if scenario.organization_id == organization_id
        )

    def list_versions(
        self,
        organization_id: OrganizationId,
        scenario_id: ScenarioDefinitionId,
    ) -> tuple[ScenarioVersionPublication, ...]:
        return tuple(
            publication
            for (stored_org_id, stored_scenario_id, _), publication in self.versions.items()
            if stored_org_id == organization_id and stored_scenario_id == scenario_id
        )


def make_policy(version: int) -> Policy:
    return Policy(
        scenario=Scenario(
            key=ScenarioKey("process_review"),
            version=ScenarioVersion(version),
            name="过程审查",
        )
    )


def test_publish_requires_exact_code_policy_and_preserves_versions() -> None:
    repository = FakeScenarioCatalogRepository()
    registry = ScenarioRegistry()
    registry.register(make_policy(1))
    registry.register(make_policy(2))
    service = ScenarioCatalogService(repository, registry)
    organization_id = OrganizationId(uuid4())
    published_at = datetime(2026, 8, 21, tzinfo=UTC)

    scenario, v1 = service.publish(
        organization_id,
        ScenarioKey("process_review"),
        ScenarioVersion(1),
        published_at=published_at,
    )
    same_scenario, v2 = service.publish(
        organization_id,
        ScenarioKey("process_review"),
        ScenarioVersion(2),
        published_at=published_at,
    )

    assert same_scenario == scenario
    assert v1.version == 1
    assert v2.version == 2
    assert repository.get_version(organization_id, scenario.id, ScenarioVersion(1)) == v1

    with pytest.raises(LookupError, match="process_review@3"):
        service.publish(
            organization_id,
            ScenarioKey("process_review"),
            ScenarioVersion(3),
        )


def test_publish_rejects_duplicate_exact_version() -> None:
    repository = FakeScenarioCatalogRepository()
    registry = ScenarioRegistry()
    registry.register(make_policy(1))
    service = ScenarioCatalogService(repository, registry)
    organization_id = OrganizationId(uuid4())
    service.publish(organization_id, ScenarioKey("process_review"), ScenarioVersion(1))

    with pytest.raises(ScenarioVersionAlreadyPublishedError):
        service.publish(organization_id, ScenarioKey("process_review"), ScenarioVersion(1))
