import argparse
import getpass
from datetime import UTC, datetime
from uuid import uuid4

from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from easyaudit_next.infrastructure.database import (
    create_database_engine,
    create_session_factory,
    session_scope,
)
from easyaudit_next.platform.application.administration import PasswordPolicyError
from easyaudit_next.platform.application.services import IdentityOrganizationService
from easyaudit_next.platform.domain.ids import PlatformAuditEventId
from easyaudit_next.platform.domain.models import (
    LocalCredential,
    PlatformAuditEvent,
    PlatformRole,
)
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyDepartmentRepository,
    SqlAlchemyLocalCredentialRepository,
    SqlAlchemyOrganizationRepository,
    SqlAlchemyPlatformAuditRepository,
    SqlAlchemyUserRepository,
)


def _ensure_bootstrap_available(session: Session) -> None:
    if SqlAlchemyOrganizationRepository(session).list_all():
        raise RuntimeError("Bootstrap refused: an Organization already exists")


def bootstrap_admin_in_session(
    session: Session,
    organization_name: str,
    admin_name: str,
    login_name: str,
    password: str,
    *,
    now: datetime | None = None,
) -> None:
    _ensure_bootstrap_available(session)
    if len(password) < 12:
        raise PasswordPolicyError("Password must contain at least 12 characters")
    organizations = SqlAlchemyOrganizationRepository(session)
    departments = SqlAlchemyDepartmentRepository(session)
    users = SqlAlchemyUserRepository(session)
    identity = IdentityOrganizationService(organizations, departments, users)
    organization = identity.create_organization(organization_name)
    admin = identity.create_user(
        organization.id,
        admin_name,
        platform_role=PlatformRole.SYSTEM_ADMIN,
    )
    occurred_at = now or datetime.now(UTC)
    SqlAlchemyLocalCredentialRepository(session).add(
        LocalCredential(
            user_id=admin.id,
            organization_id=organization.id,
            login_name=login_name.strip().lower(),
            password_hash=PasswordHash.recommended().hash(password),
            password_changed_at=occurred_at,
        )
    )
    SqlAlchemyPlatformAuditRepository(session).add(
        PlatformAuditEvent(
            id=PlatformAuditEventId(uuid4()),
            organization_id=organization.id,
            actor_user_id=admin.id,
            target_user_id=admin.id,
            event_type="bootstrap.system_admin_created",
            occurred_at=occurred_at,
        )
    )


def bootstrap_admin(organization_name: str, admin_name: str, login_name: str) -> None:
    engine = create_database_engine()
    factory = create_session_factory(engine)
    try:
        with session_scope(factory) as session:
            _ensure_bootstrap_available(session)
            password = getpass.getpass("Initial admin password: ")
            confirmation = getpass.getpass("Confirm password: ")
            if password != confirmation:
                raise PasswordPolicyError("Password confirmation does not match")
            bootstrap_admin_in_session(
                session,
                organization_name,
                admin_name,
                login_name,
                password,
            )
    finally:
        engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="easyaudit-next")
    subparsers = parser.add_subparsers(dest="command", required=True)
    bootstrap = subparsers.add_parser(
        "bootstrap-admin",
        help="Create the first Organization and system administrator without default credentials",
    )
    bootstrap.add_argument("--organization-name", required=True)
    bootstrap.add_argument("--admin-name", required=True)
    bootstrap.add_argument("--login-name", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "bootstrap-admin":
        bootstrap_admin(args.organization_name, args.admin_name, args.login_name)


if __name__ == "__main__":
    main()
