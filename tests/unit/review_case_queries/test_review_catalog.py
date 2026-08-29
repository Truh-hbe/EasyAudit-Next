from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.domain.models import PlatformRole, User
from easyaudit_next.review_case_queries.review_catalog import ReviewCatalogQueryService
from easyaudit_next.review_core.domain.models import (
    ReviewCaseLifecycle,
    Scenario,
    ScenarioDefinition,
    ScenarioKey,
    ScenarioVersion,
    ScenarioVersionPublication,
)
from easyaudit_next.review_core.domain.scenario_capabilities import (
    AuthorizationContext,
    CaseCreationDecision,
)
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry


@dataclass(frozen=True)
class CreationPolicy:
    required_permission: str = "create_case"

    def decision(self) -> CaseCreationDecision:
        return CaseCreationDecision(
            required_permission=self.required_permission,
            initial_lifecycle=ReviewCaseLifecycle.DRAFT,
            creator_role_keys=("lead",),
            activity_event_type="review_case.created",
        )


@dataclass(frozen=True)
class AuthorizationPolicy:
    allowed: bool

    def allows(self, permission: str, context: AuthorizationContext) -> bool:
        return self.allowed and context.is_active_organization_user and permission == "create_case"


@dataclass(frozen=True)
class Policy:
    scenario: Scenario
    allowed: bool = True

    case_creation: CreationPolicy = CreationPolicy()
    authorization: AuthorizationPolicy | None = None

    def __post_init__(self) -> None:
        if self.authorization is None:
            object.__setattr__(self, "authorization", AuthorizationPolicy(self.allowed))


class FakeScenarioCatalogRepository:
    def __init__(self) -> None:
        self.scenarios: list[ScenarioDefinition] = []
        self.publications: list[ScenarioVersionPublication] = []

    def add_scenario(self, scenario: ScenarioDefinition) -> None:
        self.scenarios.append(scenario)

    def add_version(self, publication: ScenarioVersionPublication) -> None:
        self.publications.append(publication)

    def list_for_organization(
        self, organization_id: OrganizationId
    ) -> tuple[ScenarioDefinition, ...]:
        return tuple(item for item in self.scenarios if item.organization_id == organization_id)

    def list_versions(
        self,
        organization_id: OrganizationId,
        scenario_id: object,
    ) -> tuple[ScenarioVersionPublication, ...]:
        return tuple(
            item
            for item in self.publications
            if item.organization_id == organization_id and item.scenario_id == scenario_id
        )


def add_published(
    repository: FakeScenarioCatalogRepository,
    organization_id: OrganizationId,
    key: str,
    version: int,
    *,
    active: bool = True,
) -> None:
    scenario_id = uuid4()
    repository.add_scenario(
        ScenarioDefinition(
            id=scenario_id,
            organization_id=organization_id,
            key=ScenarioKey(key),
            name=key,
            is_active=active,
        )
    )
    repository.add_version(
        ScenarioVersionPublication(
            id=uuid4(),
            scenario_id=scenario_id,
            organization_id=organization_id,
            version=ScenarioVersion(version),
            published_at=datetime.now(UTC),
        )
    )


def actor(organization_id: OrganizationId, *, active: bool = True) -> User:
    return User(
        id=UserId(uuid4()),
        organization_id=organization_id,
        display_name="Catalog User",
        platform_role=PlatformRole.ORDINARY_USER,
        is_active=active,
    )


def test_catalog_includes_only_active_published_exact_creatable_versions_in_order() -> None:
    organization_id = OrganizationId(uuid4())
    repository = FakeScenarioCatalogRepository()
    add_published(repository, organization_id, "zeta", 1)
    add_published(repository, organization_id, "alpha", 2)
    add_published(repository, organization_id, "inactive", 1, active=False)
    registry = ScenarioRegistry()
    registry.register(Policy(Scenario(ScenarioKey("zeta"), ScenarioVersion(1), "Zeta")))
    registry.register(Policy(Scenario(ScenarioKey("alpha"), ScenarioVersion(2), "Alpha")))
    registry.register(Policy(Scenario(ScenarioKey("inactive"), ScenarioVersion(1), "Inactive")))

    result = ReviewCatalogQueryService(repository, registry).list_creatable(actor(organization_id))

    assert [(item.scenario_key, item.scenario_version, item.display_name) for item in result] == [
        ("alpha", 2, "Alpha"),
        ("zeta", 1, "Zeta"),
    ]


def test_catalog_fails_closed_for_denied_missing_exact_and_latest_only_versions() -> None:
    organization_id = OrganizationId(uuid4())
    repository = FakeScenarioCatalogRepository()
    add_published(repository, organization_id, "denied", 1)
    add_published(repository, organization_id, "missing", 2)
    add_published(repository, organization_id, "latest_only", 2)
    registry = ScenarioRegistry()
    registry.register(Policy(Scenario(ScenarioKey("denied"), ScenarioVersion(1), "Denied"), False))
    registry.register(Policy(Scenario(ScenarioKey("latest_only"), ScenarioVersion(1), "Latest")))

    result = ReviewCatalogQueryService(repository, registry).list_creatable(actor(organization_id))

    assert result == ()


def test_catalog_does_not_expose_inactive_actor_or_other_organization() -> None:
    organization_id = OrganizationId(uuid4())
    other_organization_id = OrganizationId(uuid4())
    repository = FakeScenarioCatalogRepository()
    add_published(repository, organization_id, "process_review", 1)
    add_published(repository, other_organization_id, "other", 1)
    registry = ScenarioRegistry()
    registry.register(
        Policy(Scenario(ScenarioKey("process_review"), ScenarioVersion(1), "Process Review"))
    )
    registry.register(Policy(Scenario(ScenarioKey("other"), ScenarioVersion(1), "Other")))
    service = ReviewCatalogQueryService(repository, registry)

    assert service.list_creatable(actor(organization_id, active=False)) == ()
    assert [item.scenario_key for item in service.list_creatable(actor(organization_id))] == [
        "process_review"
    ]
