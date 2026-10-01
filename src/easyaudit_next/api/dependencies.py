from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from easyaudit_next.infrastructure.database import create_database_engine, create_session_factory
from easyaudit_next.infrastructure.observability import bind_actor
from easyaudit_next.platform.application.authentication import (
    AuthenticationService,
    InvalidSessionError,
)
from easyaudit_next.platform.application.login_throttle import (
    LoginThrottlePolicy,
    LoginThrottleService,
)
from easyaudit_next.platform.domain.models import AuthSession, PlatformRole, User
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyAuthSessionRepository,
    SqlAlchemyLocalCredentialRepository,
    SqlAlchemyLoginThrottleUnitOfWork,
    SqlAlchemyPlatformAuditRepository,
    SqlAlchemyUserRepository,
)
from easyaudit_next.platform.settings import get_settings

_engine = create_database_engine()
_session_factory = create_session_factory(_engine)


def get_business_engine() -> Engine:
    return _engine


def get_database_session() -> Iterator[Session]:
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# Request success must not be observable before the transaction it represents is committed.
# In particular, a session cookie may only leave the server after its AuthSession row exists.
DatabaseSession = Annotated[
    Session,
    Depends(get_database_session, scope="function"),
]


def get_authentication_service(
    session: DatabaseSession,
) -> AuthenticationService:
    settings = get_settings()
    return AuthenticationService(
        SqlAlchemyLocalCredentialRepository(session),
        SqlAlchemyAuthSessionRepository(session),
        SqlAlchemyUserRepository(session),
        SqlAlchemyPlatformAuditRepository(session),
        session_ttl=timedelta(seconds=settings.session_ttl_seconds),
        touch_interval=timedelta(seconds=settings.session_touch_interval_seconds),
        login_throttle=LoginThrottleService(
            SqlAlchemyLoginThrottleUnitOfWork(session.get_bind()),
            LoginThrottlePolicy(
                window=timedelta(seconds=settings.login_throttle_window_seconds),
                login_name_limit=settings.login_throttle_login_name_limit,
                ip_limit=settings.login_throttle_ip_limit,
            ),
        ),
    )


Authentication = Annotated[AuthenticationService, Depends(get_authentication_service)]


@dataclass(frozen=True, slots=True)
class CurrentIdentity:
    auth_session: AuthSession
    user: User


def get_current_identity(
    request: Request,
    auth: Authentication,
) -> Iterator[CurrentIdentity]:
    token = request.cookies.get(get_settings().session_cookie_name)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    try:
        auth_session, user = auth.authenticate(token)
    except InvalidSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        ) from exc

    bind_actor(user.organization_id, user.id)
    try:
        yield CurrentIdentity(auth_session=auth_session, user=user)
    finally:
        auth.touch(auth_session)


# CurrentIdentity reuses DatabaseSession in its exit path to touch the session. Keep both
# dependency lifetimes function-scoped so touch + commit finish before the response is sent.
AuthenticatedIdentity = Annotated[
    CurrentIdentity,
    Depends(get_current_identity, scope="function"),
]


def require_business_identity(
    identity: AuthenticatedIdentity,
    session: DatabaseSession,
) -> CurrentIdentity:
    credential = SqlAlchemyLocalCredentialRepository(session).get_by_user_id(identity.user.id)
    if credential is not None and credential.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password change required before business APIs",
        )
    return identity


BusinessIdentity = Annotated[CurrentIdentity, Depends(require_business_identity)]


def require_system_admin(
    identity: AuthenticatedIdentity,
) -> CurrentIdentity:
    if identity.user.platform_role is not PlatformRole.SYSTEM_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="system_admin required")
    return identity


SystemAdminIdentity = Annotated[CurrentIdentity, Depends(require_system_admin)]
