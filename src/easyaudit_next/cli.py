import argparse
import getpass
import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pwdlib import PasswordHash
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from easyaudit_next.composition import build_scenario_registry
from easyaudit_next.infrastructure.database import (
    create_database_engine,
    create_session_factory,
    session_scope,
)
from easyaudit_next.platform.application.authentication import normalize_login_name
from easyaudit_next.platform.application.login_throttle import (
    LoginThrottlePolicy,
    LoginThrottleService,
)
from easyaudit_next.platform.application.password_policy import (
    PasswordPolicyError,
    validate_local_password,
)
from easyaudit_next.platform.application.services import IdentityOrganizationService
from easyaudit_next.platform.domain.ids import OrganizationId, PlatformAuditEventId
from easyaudit_next.platform.domain.models import (
    LocalCredential,
    PlatformAuditEvent,
    PlatformRole,
)
from easyaudit_next.platform.persistence.models import AuthSessionRecord
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyDepartmentRepository,
    SqlAlchemyLocalCredentialRepository,
    SqlAlchemyLoginThrottleRepository,
    SqlAlchemyOrganizationRepository,
    SqlAlchemyPlatformAuditRepository,
    SqlAlchemyUserRepository,
)
from easyaudit_next.platform.settings import get_settings
from easyaudit_next.review_core.application.scenario_catalog import ScenarioCatalogService
from easyaudit_next.review_core.domain.models import ScenarioKey, ScenarioVersion
from easyaudit_next.review_core.persistence.repositories import SqlAlchemyScenarioCatalogRepository


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
    validate_local_password(password)
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


def publish_scenario_in_session(
    session: Session,
    organization_id: OrganizationId,
    scenario_key: ScenarioKey,
    scenario_version: ScenarioVersion,
) -> None:
    """Publish one exact, code-defined Scenario version for an existing Organization."""

    if SqlAlchemyOrganizationRepository(session).get(organization_id) is None:
        raise LookupError(f"Organization {organization_id} does not exist")
    ScenarioCatalogService(
        SqlAlchemyScenarioCatalogRepository(session),
        build_scenario_registry(),
    ).publish(organization_id, scenario_key, scenario_version)


def publish_scenario(
    organization_id: OrganizationId,
    scenario_key: ScenarioKey,
    scenario_version: ScenarioVersion,
) -> None:
    engine = create_database_engine()
    factory = create_session_factory(engine)
    try:
        with session_scope(factory) as session:
            publish_scenario_in_session(
                session,
                organization_id,
                scenario_key,
                scenario_version,
            )
    finally:
        engine.dispose()


def cleanup_auth_in_session(
    session: Session,
    *,
    window: timedelta,
    now: datetime | None = None,
    clear_login_name: str | None = None,
) -> dict[str, int]:
    """Delete expired login_throttle windows. Never touches auth_sessions: they are audit
    anchors (FK RESTRICT) and `expires_at` already makes an expired one unusable. The count of
    expired sessions is reported for scale only."""
    current = now or datetime.now(UTC)
    throttle = LoginThrottleService(
        lambda: nullcontext(SqlAlchemyLoginThrottleRepository(session)),
        LoginThrottlePolicy(window=window),
    )
    deleted = throttle.purge_expired(now=current)
    counts: dict[str, int] = {}
    if clear_login_name is not None:
        counts["login_name_cleared"] = throttle.clear_login_name(
            normalize_login_name(clear_login_name)
        )
    expired_sessions = session.scalar(
        select(func.count()).select_from(AuthSessionRecord).where(
            AuthSessionRecord.expires_at <= current
        )
    )
    return {
        "login_throttle_deleted": deleted,
        **counts,
        "expired_sessions": int(expired_sessions or 0),
    }


def cleanup_auth(clear_login_name: str | None = None) -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    try:
        with session_scope(factory) as session:
            counts = cleanup_auth_in_session(
                session,
                window=timedelta(seconds=settings.login_throttle_window_seconds),
                clear_login_name=clear_login_name,
            )
    finally:
        engine.dispose()
    print(json.dumps({"event": "cleanup_auth", **counts}))


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
    publish = subparsers.add_parser(
        "publish-scenario",
        help="Publish one exact code-defined Scenario version for an Organization",
    )
    publish.add_argument("--organization-id", required=True, type=UUID)
    publish.add_argument("--key", required=True, type=ScenarioKey)
    publish.add_argument("--version", required=True, type=int)
    subparsers.add_parser(
        "cleanup-auth",
        help="Delete expired login_throttle windows (sessions are kept; only counted)",
    ).add_argument(
        "--clear-login-name",
        help="Also drop every login throttle counter of this login name (unblocks it)",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "bootstrap-admin":
        bootstrap_admin(args.organization_name, args.admin_name, args.login_name)
    elif args.command == "publish-scenario":
        publish_scenario(
            OrganizationId(args.organization_id),
            ScenarioKey(args.key),
            ScenarioVersion(args.version),
        )
    elif args.command == "cleanup-auth":
        cleanup_auth(args.clear_login_name)


if __name__ == "__main__":
    main()
