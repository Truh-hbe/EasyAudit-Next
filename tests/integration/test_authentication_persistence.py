import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pwdlib import PasswordHash
from sqlalchemy import Engine, create_engine, delete, inspect, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from easyaudit_next.platform.application.authentication import (
    AuthenticationService,
    InvalidSessionError,
)
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.domain.models import LocalCredential, PlatformRole, User
from easyaudit_next.platform.persistence.models import (
    LocalCredentialRecord,
    OrganizationRecord,
    PlatformAuditEventRecord,
    UserRecord,
)
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyAuthSessionRepository,
    SqlAlchemyLocalCredentialRepository,
    SqlAlchemyPlatformAuditRepository,
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


def test_migration_creates_authentication_and_audit_tables(postgres_engine: Engine) -> None:
    assert {"local_credentials", "auth_sessions", "platform_audit_events"} <= set(
        inspect(postgres_engine).get_table_names()
    )


def create_local_user(session: Session, login_name: str = "m12-admin") -> tuple[User, str]:
    organization_id = OrganizationId(uuid4())
    user_id = UserId(uuid4())
    password = "correct-horse-battery"
    password_hash = PasswordHash.recommended().hash(password)
    session.add(OrganizationRecord(id=organization_id, name=f"Organization {login_name}"))
    session.flush()
    session.add(
        UserRecord(
            id=user_id,
            organization_id=organization_id,
            display_name="M1.2 Admin",
            platform_role="system_admin",
        )
    )
    session.flush()
    SqlAlchemyLocalCredentialRepository(session).add(
        LocalCredential(
            user_id=user_id,
            organization_id=organization_id,
            login_name=login_name,
            password_hash=password_hash,
            password_changed_at=datetime.now(UTC),
        )
    )
    return (
        User(
            id=user_id,
            organization_id=organization_id,
            display_name="M1.2 Admin",
            platform_role=PlatformRole.SYSTEM_ADMIN,
        ),
        password,
    )


def auth_service(session: Session) -> AuthenticationService:
    return AuthenticationService(
        SqlAlchemyLocalCredentialRepository(session),
        SqlAlchemyAuthSessionRepository(session),
        SqlAlchemyUserRepository(session),
        SqlAlchemyPlatformAuditRepository(session),
    )


def test_argon2id_login_logout_and_audit_round_trip(session: Session) -> None:
    user, password = create_local_user(session)
    credential = session.scalar(
        select(LocalCredentialRecord).where(LocalCredentialRecord.user_id == user.id)
    )
    assert credential is not None
    assert credential.password_hash.startswith("$argon2id$")
    assert password not in credential.password_hash

    service = auth_service(session)
    result = service.login("M12-ADMIN", password)
    assert result.user == user
    assert result.auth_session.token_hash == service.hash_token(result.token)
    assert result.token != result.auth_session.token_hash

    service.logout(result.auth_session, result.user)
    with pytest.raises(InvalidSessionError):
        service.authenticate(result.token)

    event_types = set(session.scalars(select(PlatformAuditEventRecord.event_type)))
    assert {"auth.login_succeeded", "auth.session_revoked"} <= event_types


def test_disabled_user_cannot_reuse_existing_session(session: Session) -> None:
    user, password = create_local_user(session, "disabled-user")
    service = auth_service(session)
    result = service.login("disabled-user", password)
    SqlAlchemyUserRepository(session).update(
        User(
            id=user.id,
            organization_id=user.organization_id,
            display_name=user.display_name,
            platform_role=user.platform_role,
            is_active=False,
        )
    )

    with pytest.raises(InvalidSessionError):
        service.authenticate(result.token)


def test_database_rejects_cross_organization_credential(session: Session) -> None:
    organization_a_id = uuid4()
    organization_b_id = uuid4()
    user_id = uuid4()
    session.add_all(
        [
            OrganizationRecord(id=organization_a_id, name="Credential Organization A"),
            OrganizationRecord(id=organization_b_id, name="Credential Organization B"),
        ]
    )
    session.flush()
    session.add(
        UserRecord(
            id=user_id,
            organization_id=organization_a_id,
            display_name="Credential User",
            platform_role="ordinary_user",
        )
    )
    session.flush()
    session.add(
        LocalCredentialRecord(
            user_id=user_id,
            organization_id=organization_b_id,
            login_name="cross-organization",
            password_hash="$argon2id$invalid-but-not-plain",
            password_changed_at=datetime.now(UTC),
        )
    )

    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize("statement", ["update", "delete"])
def test_platform_audit_events_are_append_only(session: Session, statement: str) -> None:
    user, password = create_local_user(session, f"audit-{statement}")
    auth_service(session).login(f"audit-{statement}", password)
    event_id = session.scalar(
        select(PlatformAuditEventRecord.id)
        .where(PlatformAuditEventRecord.organization_id == user.organization_id)
        .limit(1)
    )
    assert event_id is not None
    command = (
        update(PlatformAuditEventRecord)
        .where(PlatformAuditEventRecord.id == event_id)
        .values(event_type="tampered")
        if statement == "update"
        else delete(PlatformAuditEventRecord).where(PlatformAuditEventRecord.id == event_id)
    )

    with pytest.raises(DBAPIError):
        session.execute(command)
