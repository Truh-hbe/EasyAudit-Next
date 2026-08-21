import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from easyaudit_next.platform.application.services import IdentityOrganizationService
from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId
from easyaudit_next.platform.persistence.models import (
    DepartmentRecord,
    OrganizationRecord,
    UserRecord,
)
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyDepartmentRepository,
    SqlAlchemyOrganizationRepository,
    SqlAlchemyUserRepository,
)


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


def test_migration_creates_identity_organization_tables(postgres_engine: Engine) -> None:
    table_names = set(inspect(postgres_engine).get_table_names())
    assert {"organizations", "departments", "users"} <= table_names


def test_sqlalchemy_repositories_round_trip_domain_entities(session: Session) -> None:
    organization_repository = SqlAlchemyOrganizationRepository(session)
    department_repository = SqlAlchemyDepartmentRepository(session)
    user_repository = SqlAlchemyUserRepository(session)
    service = IdentityOrganizationService(
        organization_repository,
        department_repository,
        user_repository,
    )

    organization = service.create_organization("Repository Round Trip")
    department = service.create_department(organization.id, "Quality")
    user = service.create_user(
        organization.id,
        "Repository User",
        primary_department_id=department.id,
    )

    assert organization_repository.get(organization.id) == organization
    assert department_repository.get(department.id) == department
    assert user_repository.get(user.id) == user


def test_database_rejects_cross_organization_department_parent(session: Session) -> None:
    organization_a_id = uuid4()
    organization_b_id = uuid4()
    parent_id = uuid4()
    session.add_all(
        [
            OrganizationRecord(id=organization_a_id, name="Organization A"),
            OrganizationRecord(id=organization_b_id, name="Organization B"),
        ]
    )
    session.flush()
    session.add(
        DepartmentRecord(
            id=parent_id,
            organization_id=organization_b_id,
            name="Parent B",
        )
    )
    session.flush()

    session.add(
        DepartmentRecord(
            id=uuid4(),
            organization_id=organization_a_id,
            parent_id=parent_id,
            name="Child A",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_database_rejects_cross_organization_primary_department(session: Session) -> None:
    organization_a_id = uuid4()
    organization_b_id = uuid4()
    department_b_id = uuid4()
    session.add_all(
        [
            OrganizationRecord(id=organization_a_id, name="Organization A"),
            OrganizationRecord(id=organization_b_id, name="Organization B"),
        ]
    )
    session.flush()
    session.add(
        DepartmentRecord(
            id=department_b_id,
            organization_id=organization_b_id,
            name="Department B",
        )
    )
    session.flush()

    session.add(
        UserRecord(
            id=uuid4(),
            organization_id=organization_a_id,
            primary_department_id=department_b_id,
            display_name="Cross-boundary User",
            platform_role="ordinary_user",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_database_rejects_department_cycle(session: Session) -> None:
    organization_id = uuid4()
    root_id = uuid4()
    child_id = uuid4()
    session.add(OrganizationRecord(id=organization_id, name="Cycle Organization"))
    session.flush()
    root = DepartmentRecord(id=root_id, organization_id=organization_id, name="Root")
    child = DepartmentRecord(
        id=child_id,
        organization_id=organization_id,
        parent_id=root_id,
        name="Child",
    )
    session.add_all([root, child])
    session.flush()

    root.parent_id = child_id
    with pytest.raises(IntegrityError):
        session.flush()


def test_repository_rejects_wrong_uuid_type_before_database(session: Session) -> None:
    repository = SqlAlchemyDepartmentRepository(session)
    assert repository.get(DepartmentId(uuid4())) is None
    assert SqlAlchemyOrganizationRepository(session).get(OrganizationId(uuid4())) is None
