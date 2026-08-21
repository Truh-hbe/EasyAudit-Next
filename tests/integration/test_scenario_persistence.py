import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, delete, inspect, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from easyaudit_next.platform.domain.ids import OrganizationId
from easyaudit_next.platform.persistence.models import OrganizationRecord
from easyaudit_next.review_core.application.scenario_catalog import ScenarioCatalogService
from easyaudit_next.review_core.domain.models import (
    Scenario,
    ScenarioKey,
    ScenarioVersion,
)
from easyaudit_next.review_core.domain.scenario_registry import ScenarioRegistry
from easyaudit_next.review_core.persistence.models import ScenarioRecord, ScenarioVersionRecord
from easyaudit_next.review_core.persistence.repositories import SqlAlchemyScenarioCatalogRepository


@dataclass(frozen=True)
class Policy:
    scenario: Scenario
    case_role_keys: tuple[str, ...] = ("lead",)
    finding_participant_role_keys: tuple[str, ...] = ("owner",)

    def validate_case_input(self, payload: Mapping[str, object]) -> tuple[str, ...]:
        return ()


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    if os.getenv("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in outside CI")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def session(postgres_engine: Engine) -> Iterator[Session]:
    connection = postgres_engine.connect()
    transaction = connection.begin()
    database_session = Session(bind=connection, expire_on_commit=False)
    try:
        yield database_session
    finally:
        database_session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def test_migration_creates_scenario_catalog_tables(postgres_engine: Engine) -> None:
    assert {"scenarios", "scenario_versions"} <= set(inspect(postgres_engine).get_table_names())


def test_repository_round_trip_preserves_historical_version(session: Session) -> None:
    organization_id = OrganizationId(uuid4())
    session.add(OrganizationRecord(id=organization_id, name="Scenario Organization"))
    session.flush()
    registry = ScenarioRegistry()
    for version in (1, 2):
        registry.register(
            Policy(
                Scenario(
                    key=ScenarioKey("process_review"),
                    version=ScenarioVersion(version),
                    name="过程审查",
                )
            )
        )
    repository = SqlAlchemyScenarioCatalogRepository(session)
    service = ScenarioCatalogService(repository, registry)
    _, v1 = service.publish(organization_id, ScenarioKey("process_review"), ScenarioVersion(1))
    scenario, _ = service.publish(
        organization_id, ScenarioKey("process_review"), ScenarioVersion(2)
    )

    assert repository.get_version(scenario.id, ScenarioVersion(1)) == v1
    assert repository.list_for_organization(organization_id) == (scenario,)
    assert [item.version for item in repository.list_versions(scenario.id)] == [1, 2]


def test_database_rejects_cross_organization_scenario_version(session: Session) -> None:
    organization_a_id = uuid4()
    organization_b_id = uuid4()
    scenario_id = uuid4()
    session.add_all(
        [
            OrganizationRecord(id=organization_a_id, name="Organization A"),
            OrganizationRecord(id=organization_b_id, name="Organization B"),
        ]
    )
    session.flush()
    session.add(
        ScenarioRecord(
            id=scenario_id,
            organization_id=organization_a_id,
            key="process_review",
            name="过程审查",
        )
    )
    session.flush()
    session.add(
        ScenarioVersionRecord(
            id=uuid4(),
            scenario_id=scenario_id,
            organization_id=organization_b_id,
            version=1,
            published_at=datetime.now(UTC),
        )
    )

    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize("statement", ["update", "delete"])
def test_database_rejects_scenario_version_mutation(session: Session, statement: str) -> None:
    organization_id = uuid4()
    scenario_id = uuid4()
    version_id = uuid4()
    session.add(OrganizationRecord(id=organization_id, name=f"Immutable {statement}"))
    session.flush()
    session.add(
        ScenarioRecord(
            id=scenario_id,
            organization_id=organization_id,
            key=f"scenario_{statement}",
            name="Immutable Scenario",
        )
    )
    session.flush()
    session.add(
        ScenarioVersionRecord(
            id=version_id,
            scenario_id=scenario_id,
            organization_id=organization_id,
            version=1,
            published_at=datetime.now(UTC),
        )
    )
    session.flush()

    command = (
        update(ScenarioVersionRecord)
        .where(ScenarioVersionRecord.id == version_id)
        .values(version=2)
        if statement == "update"
        else delete(ScenarioVersionRecord).where(ScenarioVersionRecord.id == version_id)
    )
    with pytest.raises(DBAPIError):
        session.execute(command)
