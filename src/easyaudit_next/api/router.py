from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from easyaudit_next.api.contracts import (
    AdminScenarioStatusItem,
    AdminScenarioStatusResponse,
    AdminScenarioVersionStatus,
    CredentialResetRequest,
    CurrentUserResponse,
    DepartmentCreateRequest,
    DepartmentPatchRequest,
    DepartmentResponse,
    DomainModelResponse,
    LoginRequest,
    LoginResponse,
    OrganizationResponse,
    PasswordChangeRequest,
    ScenarioResponse,
    ScenarioVersionResponse,
    SessionResponse,
    UserCreateRequest,
    UserPatchRequest,
    UserResponse,
)
from easyaudit_next.api.dependencies import (
    AuthenticatedIdentity,
    Authentication,
    DatabaseSession,
    SystemAdminIdentity,
)
from easyaudit_next.api.errors import CodedHTTPException, raise_database_conflict
from easyaudit_next.application.case_team_coordination import UserDeactivationConflictError
from easyaudit_next.composition import (
    build_case_team_coordinator,
    build_platform_administration_service,
    build_scenario_registry,
)
from easyaudit_next.infrastructure.observability import APP_LOGGER
from easyaudit_next.platform.application.administration import PlatformAdministrationService
from easyaudit_next.platform.application.authentication import (
    InvalidCredentialsError,
    InvalidCurrentPasswordError,
    InvalidSessionError,
    LocalCredentialUnavailableError,
)
from easyaudit_next.platform.application.login_throttle import LoginThrottledError
from easyaudit_next.platform.domain.ids import AuthSessionId, DepartmentId, UserId
from easyaudit_next.platform.domain.models import Department, User
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyAuthSessionRepository,
    SqlAlchemyDepartmentRepository,
    SqlAlchemyLocalCredentialRepository,
    SqlAlchemyOrganizationRepository,
    SqlAlchemyUserRepository,
)
from easyaudit_next.platform.settings import get_settings
from easyaudit_next.review_core.domain.models import ScenarioKey, ScenarioVersion
from easyaudit_next.review_core.persistence.repositories import (
    SqlAlchemyScenarioCatalogRepository,
)
from easyaudit_next.rules import RuleCode

api_router = APIRouter()

CORE_CONCEPTS = (
    "Organization",
    "Department",
    "User",
    "Scenario",
    "ReviewPlan",
    "ReviewCase",
    "Finding",
    "ActionItem",
    "CaseMember",
    "FindingParticipant",
    "ActionAssignee",
    "Activity",
    "Submission",
)


@api_router.get(
    "/api/v1/meta/domain-model",
    response_model=DomainModelResponse,
    operation_id="getDomainModel",
    tags=["meta"],
)
def get_domain_model() -> DomainModelResponse:
    return DomainModelResponse(
        stage="M1.4",
        concepts=CORE_CONCEPTS,
        backend="Python/FastAPI",
        next="M1 Final Review",
    )


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        organization_id=user.organization_id,
        display_name=user.display_name,
        platform_role=user.platform_role,
        primary_department_id=user.primary_department_id,
        is_active=user.is_active,
    )


def _current_user_response(user: User, must_change_password: bool) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=user.id,
        organization_id=user.organization_id,
        display_name=user.display_name,
        platform_role=user.platform_role,
        primary_department_id=user.primary_department_id,
        is_active=user.is_active,
        must_change_password=must_change_password,
    )


def _department_response(department: Department) -> DepartmentResponse:
    return DepartmentResponse(
        id=department.id,
        organization_id=department.organization_id,
        name=department.name,
        parent_id=department.parent_id,
        is_active=department.is_active,
    )


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=get_settings().session_cookie_name,
        value=token,
        secure=True,
        httponly=True,
        samesite="strict",
        path="/",
    )


def _administration_service(session: Session) -> PlatformAdministrationService:
    return build_platform_administration_service(session)


@api_router.post(
    "/api/v1/auth/login",
    response_model=LoginResponse,
    operation_id="login",
    tags=["auth"],
    responses={
        401: {"description": "Invalid login name or password (one answer for every cause)."},
        429: {
            "description": "Too many login attempts; `Retry-After` is the window remainder.",
            "headers": {"Retry-After": {"schema": {"type": "integer"}}},
        }
    },
)
def login(
    request: Request,
    payload: LoginRequest,
    response: Response,
    auth: Authentication,
    session: DatabaseSession,
) -> LoginResponse:
    client_ip = request.client.host if request.client else None
    try:
        result = auth.login(payload.login_name, payload.password, client_ip=client_ip)
    except LoginThrottledError as exc:
        # The attempt counters are the point of throttling: make them durable although the
        # request fails. Body and headers depend only on the window, never on the account.
        session.commit()
        for scope in exc.scopes:
            APP_LOGGER.warning("login_throttled", extra={"fields": {"throttle_scope": scope}})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except InvalidCredentialsError as exc:
        # Authentication failures are audit facts even though the HTTP request fails.
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid login name or password",
        ) from exc
    _set_session_cookie(response, result.token)
    return LoginResponse(
        user=_user_response(result.user),
        session_id=result.auth_session.id,
        expires_at=result.auth_session.expires_at,
    )


@api_router.post(
    "/api/v1/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="logout",
    tags=["auth"],
)
def logout(
    response: Response,
    identity: AuthenticatedIdentity,
    auth: Authentication,
) -> None:
    auth.logout(identity.auth_session, identity.user)
    response.delete_cookie(
        get_settings().session_cookie_name,
        secure=True,
        httponly=True,
        samesite="strict",
        path="/",
    )


@api_router.get(
    "/api/v1/me",
    response_model=CurrentUserResponse,
    operation_id="getMe",
    tags=["me"],
)
def get_me(
    identity: AuthenticatedIdentity,
    session: DatabaseSession,
) -> CurrentUserResponse:
    credential = SqlAlchemyLocalCredentialRepository(session).get_by_user_id(identity.user.id)
    return _current_user_response(
        identity.user,
        credential.must_change_password if credential is not None else False,
    )


@api_router.post(
    "/api/v1/me/password",
    response_model=CurrentUserResponse,
    operation_id="changeMyPassword",
    tags=["me"],
)
def change_my_password(
    payload: PasswordChangeRequest,
    response: Response,
    identity: AuthenticatedIdentity,
    auth: Authentication,
) -> CurrentUserResponse:
    try:
        result = auth.change_password(
            identity.auth_session,
            identity.user,
            payload.current_password,
            payload.new_password,
        )
    except InvalidCurrentPasswordError as exc:
        raise CodedHTTPException(
            status.HTTP_400_BAD_REQUEST,
            RuleCode.PASSWORD_CURRENT_INVALID,
            "Current password is invalid",
        ) from exc
    except LocalCredentialUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Local credential is unavailable",
        ) from exc
    except InvalidSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        ) from exc

    _set_session_cookie(response, result.token)
    return _current_user_response(result.user, False)


@api_router.get(
    "/api/v1/me/sessions",
    response_model=list[SessionResponse],
    operation_id="listMySessions",
    tags=["me"],
)
def list_my_sessions(
    identity: AuthenticatedIdentity,
    session: DatabaseSession,
) -> list[SessionResponse]:
    sessions = SqlAlchemyAuthSessionRepository(session).list_for_user(identity.user.id)
    return [
        SessionResponse(
            id=item.id,
            created_at=item.created_at,
            expires_at=item.expires_at,
            revoked_at=item.revoked_at,
            last_seen_at=item.last_seen_at,
            current=item.id == identity.auth_session.id,
        )
        for item in sessions
    ]


@api_router.delete(
    "/api/v1/me/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="revokeMySession",
    tags=["me"],
)
def revoke_my_session(
    session_id: UUID,
    identity: AuthenticatedIdentity,
    auth: Authentication,
    session: DatabaseSession,
) -> None:
    target = SqlAlchemyAuthSessionRepository(session).get(AuthSessionId(session_id))
    if target is None or target.user_id != identity.user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    auth.logout(target, identity.user)


@api_router.get(
    "/api/v1/admin/organization",
    response_model=OrganizationResponse,
    operation_id="getAdminOrganization",
    tags=["admin"],
)
def get_admin_organization(
    identity: SystemAdminIdentity,
    session: DatabaseSession,
) -> OrganizationResponse:
    organization = SqlAlchemyOrganizationRepository(session).get(identity.user.organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return OrganizationResponse(
        id=organization.id,
        name=organization.name,
        is_active=organization.is_active,
    )


@api_router.get(
    "/api/v1/admin/departments",
    response_model=list[DepartmentResponse],
    operation_id="listAdminDepartments",
    tags=["admin"],
)
def list_admin_departments(
    identity: SystemAdminIdentity,
    session: DatabaseSession,
) -> list[DepartmentResponse]:
    departments = SqlAlchemyDepartmentRepository(session).list_for_organization(
        identity.user.organization_id
    )
    return [_department_response(department) for department in departments]


@api_router.post(
    "/api/v1/admin/departments",
    response_model=DepartmentResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createAdminDepartment",
    tags=["admin"],
)
def create_admin_department(
    payload: DepartmentCreateRequest,
    identity: SystemAdminIdentity,
    session: DatabaseSession,
) -> DepartmentResponse:
    try:
        department = _administration_service(session).create_department(
            identity.user,
            payload.name,
            parent_id=DepartmentId(payload.parent_id) if payload.parent_id else None,
        )
    except IntegrityError as exc:
        raise_database_conflict(exc)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _department_response(department)


@api_router.patch(
    "/api/v1/admin/departments/{department_id}",
    response_model=DepartmentResponse,
    operation_id="updateAdminDepartment",
    tags=["admin"],
)
def update_admin_department(
    department_id: UUID,
    payload: DepartmentPatchRequest,
    identity: SystemAdminIdentity,
    session: DatabaseSession,
) -> DepartmentResponse:
    try:
        department = _administration_service(session).update_department(
            identity.user,
            DepartmentId(department_id),
            name=payload.name,
            parent_id=DepartmentId(payload.parent_id) if payload.parent_id else None,
            set_parent="parent_id" in payload.model_fields_set,
            is_active=payload.is_active,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise_database_conflict(exc)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _department_response(department)


@api_router.get(
    "/api/v1/admin/users",
    response_model=list[UserResponse],
    operation_id="listAdminUsers",
    tags=["admin"],
)
def list_admin_users(
    identity: SystemAdminIdentity,
    session: DatabaseSession,
) -> list[UserResponse]:
    users = SqlAlchemyUserRepository(session).list_for_organization(identity.user.organization_id)
    return [_user_response(user) for user in users]


@api_router.post(
    "/api/v1/admin/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createAdminUser",
    tags=["admin"],
)
def create_admin_user(
    payload: UserCreateRequest,
    identity: SystemAdminIdentity,
    session: DatabaseSession,
) -> UserResponse:
    try:
        user = _administration_service(session).create_local_user(
            identity.user,
            payload.display_name,
            payload.login_name,
            payload.initial_password,
            primary_department_id=(
                DepartmentId(payload.primary_department_id)
                if payload.primary_department_id
                else None
            ),
            platform_role=payload.platform_role,
            must_change_password=payload.must_change_password,
        )
    except IntegrityError as exc:
        raise_database_conflict(exc)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _user_response(user)


@api_router.get(
    "/api/v1/admin/users/{user_id}",
    response_model=UserResponse,
    operation_id="getAdminUser",
    tags=["admin"],
)
def get_admin_user(
    user_id: UUID,
    identity: SystemAdminIdentity,
    session: DatabaseSession,
) -> UserResponse:
    user = SqlAlchemyUserRepository(session).get(UserId(user_id))
    if user is None or user.organization_id != identity.user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _user_response(user)


@api_router.patch(
    "/api/v1/admin/users/{user_id}",
    response_model=UserResponse,
    operation_id="updateAdminUser",
    tags=["admin"],
)
def update_admin_user(
    user_id: UUID,
    payload: UserPatchRequest,
    identity: SystemAdminIdentity,
    session: DatabaseSession,
) -> UserResponse:
    try:
        user = build_case_team_coordinator(session).update_user(
            identity.user,
            UserId(user_id),
            display_name=payload.display_name,
            primary_department_id=(
                DepartmentId(payload.primary_department_id)
                if payload.primary_department_id
                else None
            ),
            set_primary_department="primary_department_id" in payload.model_fields_set,
            platform_role=payload.platform_role,
            is_active=payload.is_active,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UserDeactivationConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise_database_conflict(exc)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _user_response(user)


@api_router.post(
    "/api/v1/admin/users/{user_id}/credential-reset",
    response_model=UserResponse,
    operation_id="resetAdminUserCredential",
    tags=["admin"],
)
def reset_admin_user_credential(
    user_id: UUID,
    payload: CredentialResetRequest,
    identity: SystemAdminIdentity,
    session: DatabaseSession,
) -> UserResponse:
    try:
        user = _administration_service(session).reset_local_credential(
            identity.user,
            UserId(user_id),
            payload.temporary_password,
        )
    except LocalCredentialUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Local credential is unavailable",
        ) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc
    return _user_response(user)


@api_router.get(
    "/api/v1/admin/scenarios",
    response_model=list[ScenarioResponse],
    operation_id="listAdminScenarios",
    tags=["admin"],
)
def list_admin_scenarios(
    identity: SystemAdminIdentity,
    session: DatabaseSession,
) -> list[ScenarioResponse]:
    scenarios = SqlAlchemyScenarioCatalogRepository(session).list_for_organization(
        identity.user.organization_id
    )
    return [
        ScenarioResponse(
            id=scenario.id,
            organization_id=scenario.organization_id,
            key=scenario.key,
            name=scenario.name,
            is_active=scenario.is_active,
        )
        for scenario in scenarios
    ]


@api_router.get(
    "/api/v1/admin/scenarios/{key}/versions",
    response_model=list[ScenarioVersionResponse],
    operation_id="listAdminScenarioVersions",
    tags=["admin"],
)
def list_admin_scenario_versions(
    key: str,
    identity: SystemAdminIdentity,
    session: DatabaseSession,
) -> list[ScenarioVersionResponse]:
    repository = SqlAlchemyScenarioCatalogRepository(session)
    scenario = repository.get_by_key(identity.user.organization_id, ScenarioKey(key))
    if scenario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")
    return [
        ScenarioVersionResponse(
            id=publication.id,
            scenario_id=publication.scenario_id,
            version=publication.version,
            published_at=publication.published_at,
        )
        for publication in repository.list_versions(identity.user.organization_id, scenario.id)
    ]


@api_router.get(
    "/api/v1/admin/scenario-status",
    response_model=AdminScenarioStatusResponse,
    operation_id="getAdminScenarioStatus",
    tags=["admin"],
)
def get_admin_scenario_status(
    identity: SystemAdminIdentity,
    session: DatabaseSession,
) -> AdminScenarioStatusResponse:
    repository = SqlAlchemyScenarioCatalogRepository(session)
    registry = build_scenario_registry()
    items: list[AdminScenarioStatusItem] = []
    for scenario in repository.list_for_organization(identity.user.organization_id):
        versions: list[AdminScenarioVersionStatus] = []
        for publication in repository.list_versions(
            identity.user.organization_id,
            scenario.id,
        ):
            try:
                registry.get(scenario.key, ScenarioVersion(publication.version))
            except LookupError:
                registry_present = False
            else:
                registry_present = True
            versions.append(
                AdminScenarioVersionStatus(
                    scenario_version=publication.version,
                    published_at=publication.published_at,
                    registry_present=registry_present,
                    ready=scenario.is_active and registry_present,
                )
            )
        items.append(
            AdminScenarioStatusItem(
                scenario_key=scenario.key,
                display_name=scenario.name,
                is_active=scenario.is_active,
                versions=versions,
            )
        )
    return AdminScenarioStatusResponse(items=items)
