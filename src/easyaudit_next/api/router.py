from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from easyaudit_next.api.contracts import (
    DepartmentCreateRequest,
    DepartmentPatchRequest,
    DepartmentResponse,
    DomainModelResponse,
    HealthResponse,
    LoginRequest,
    LoginResponse,
    OrganizationResponse,
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
from easyaudit_next.platform.application.administration import PlatformAdministrationService
from easyaudit_next.platform.application.authentication import (
    AuthenticationService,
    InvalidCredentialsError,
)
from easyaudit_next.platform.application.services import IdentityOrganizationService
from easyaudit_next.platform.domain.ids import AuthSessionId, DepartmentId, UserId
from easyaudit_next.platform.domain.models import Department, User
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyAuthSessionRepository,
    SqlAlchemyDepartmentRepository,
    SqlAlchemyLocalCredentialRepository,
    SqlAlchemyOrganizationRepository,
    SqlAlchemyPlatformAuditRepository,
    SqlAlchemyUserRepository,
)
from easyaudit_next.platform.settings import get_settings
from easyaudit_next.review_core.domain.models import ScenarioKey
from easyaudit_next.review_core.persistence.repositories import (
    SqlAlchemyScenarioCatalogRepository,
)

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
    "/health",
    response_model=HealthResponse,
    operation_id="getHealth",
    tags=["system"],
)
def get_health() -> HealthResponse:
    return HealthResponse(status="ok", stage="M1.4")


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


def _department_response(department: Department) -> DepartmentResponse:
    return DepartmentResponse(
        id=department.id,
        organization_id=department.organization_id,
        name=department.name,
        parent_id=department.parent_id,
        is_active=department.is_active,
    )


def _administration_service(session: Session) -> PlatformAdministrationService:
    organizations = SqlAlchemyOrganizationRepository(session)
    departments = SqlAlchemyDepartmentRepository(session)
    users = SqlAlchemyUserRepository(session)
    credentials = SqlAlchemyLocalCredentialRepository(session)
    audit = SqlAlchemyPlatformAuditRepository(session)
    auth = AuthenticationService(
        credentials,
        SqlAlchemyAuthSessionRepository(session),
        users,
        audit,
    )
    return PlatformAdministrationService(
        IdentityOrganizationService(organizations, departments, users),
        organizations,
        departments,
        users,
        credentials,
        auth,
        audit,
    )


@api_router.post(
    "/api/v1/auth/login",
    response_model=LoginResponse,
    operation_id="login",
    tags=["auth"],
)
def login(
    payload: LoginRequest,
    response: Response,
    auth: Authentication,
    session: DatabaseSession,
) -> LoginResponse:
    try:
        result = auth.login(payload.login_name, payload.password)
    except InvalidCredentialsError as exc:
        # Authentication failures are audit facts even though the HTTP request fails.
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid login name or password",
        ) from exc
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=result.token,
        secure=True,
        httponly=True,
        samesite="strict",
        path="/",
    )
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
    response_model=UserResponse,
    operation_id="getMe",
    tags=["me"],
)
def get_me(identity: AuthenticatedIdentity) -> UserResponse:
    return _user_response(identity.user)


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
    except (LookupError, ValueError, IntegrityError) as exc:
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
    except (ValueError, IntegrityError) as exc:
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
    except (ValueError, IntegrityError) as exc:
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
        user = _administration_service(session).update_user(
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
    except (ValueError, IntegrityError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
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
        for publication in repository.list_versions(scenario.id)
    ]
