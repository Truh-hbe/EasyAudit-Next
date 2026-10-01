from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session

from easyaudit_next.api.dependencies import (
    CurrentIdentity,
    get_current_identity,
    get_database_session,
)
from easyaudit_next.application.case_team_coordination import UserDeactivationConflictError
from easyaudit_next.composition import build_case_team_coordinator, build_scenario_registry
from easyaudit_next.main import create_app
from easyaudit_next.platform.domain.ids import AuthSessionId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import AuthSession, User
from easyaudit_next.platform.persistence.models import (
    AuthSessionRecord,
    LocalCredentialRecord,
    OrganizationRecord,
    PlatformAuditEventRecord,
    UserRecord,
)
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.application.review_planning import (
    CaseManagerConflictError,
    ReviewAuthorizationError,
    ReviewPlanningService,
    effective_case_manager_ids,
)
from easyaudit_next.review_core.domain.ids import ReviewCaseId
from easyaudit_next.review_core.domain.models import ScenarioKey, ScenarioVersion
from easyaudit_next.review_core.persistence.models import (
    ActivityRecord,
    CaseMemberRecord,
    ScenarioRecord,
    ScenarioVersionRecord,
)
from easyaudit_next.review_core.persistence.repositories import (
    SqlAlchemyReviewCoreRepository,
    SqlAlchemyScenarioCatalogRepository,
)

if os.environ.get("EASYAUDIT_RUN_POSTGRES_TESTS") != "1":
    pytestmark = pytest.mark.skip(reason="PostgreSQL integration tests are opt-in outside CI")

PASSWORD_HASH = PasswordHash.recommended()
NOW = datetime(2026, 8, 30, 2, 0, tzinfo=UTC)


@dataclass(frozen=True)
class TeamFixture:
    organization_id: OrganizationId
    manager_id: UserId
    second_manager_id: UserId
    candidate_id: UserId
    inactive_id: UserId
    non_manager_id: UserId
    admin_id: UserId
    foreign_user_id: UserId


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    yield engine
    engine.dispose()


def _seed_fixture(engine: Engine, *, scenario_key: str = "process_review") -> TeamFixture:
    organization_id = OrganizationId(uuid4())
    ids = {name: UserId(uuid4()) for name in (
        "manager",
        "second_manager",
        "candidate",
        "inactive",
        "non_manager",
        "admin",
        "foreign",
    )}
    foreign_organization_id = OrganizationId(uuid4())
    scenario_id = uuid4()
    version_id = uuid4()
    users = (
        (ids["manager"], "Manager", "ordinary_user", True),
        (ids["second_manager"], "Second Manager", "ordinary_user", True),
        (ids["candidate"], "Candidate User", "ordinary_user", True),
        (ids["inactive"], "Inactive User", "ordinary_user", False),
        (ids["non_manager"], "Non Manager", "ordinary_user", True),
        (ids["admin"], "System Admin", "system_admin", True),
    )
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                OrganizationRecord(id=organization_id, name=f"M5.3 {organization_id}"),
                OrganizationRecord(
                    id=foreign_organization_id,
                    name=f"Foreign {foreign_organization_id}",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                UserRecord(
                    id=user_id,
                    organization_id=organization_id,
                    display_name=display_name,
                    platform_role=platform_role,
                    is_active=is_active,
                )
                for user_id, display_name, platform_role, is_active in users
            ]
            + [
                UserRecord(
                    id=ids["foreign"],
                    organization_id=foreign_organization_id,
                    display_name="Foreign Candidate",
                    platform_role="ordinary_user",
                )
            ]
        )
        session.flush()
        session.add_all(
            [
                LocalCredentialRecord(
                    user_id=user_id,
                    organization_id=organization_id,
                    login_name=f"m53-{name}-{user_id.hex}",
                    password_hash=PASSWORD_HASH.hash("unused-m5-3-password"),
                    password_changed_at=NOW,
                    must_change_password=False,
                )
                for name, (user_id, _, _, _) in zip(
                    ("manager", "second-manager", "candidate", "inactive", "non-manager", "admin"),
                    users,
                    strict=True,
                )
            ]
        )
        session.flush()
        session.add_all(
            [
                ScenarioRecord(
                    id=scenario_id,
                    organization_id=organization_id,
                    key=scenario_key,
                    name=scenario_key.replace("_", " ").title(),
                ),
                ScenarioVersionRecord(
                    id=version_id,
                    scenario_id=scenario_id,
                    organization_id=organization_id,
                    version=1,
                    published_at=NOW,
                ),
            ]
        )
    return TeamFixture(
        organization_id=organization_id,
        manager_id=ids["manager"],
        second_manager_id=ids["second_manager"],
        candidate_id=ids["candidate"],
        inactive_id=ids["inactive"],
        non_manager_id=ids["non_manager"],
        admin_id=ids["admin"],
        foreign_user_id=ids["foreign"],
    )


def _service(session: Session) -> ReviewPlanningService:
    return ReviewPlanningService(
        SqlAlchemyReviewCoreRepository(session),
        SqlAlchemyScenarioCatalogRepository(session),
        SqlAlchemyUserRepository(session),
        build_scenario_registry(),
    )


def _create_case(session: Session, fixture: TeamFixture, scenario_key: str) -> ReviewCaseId:
    users = SqlAlchemyUserRepository(session)
    manager = users.get(fixture.manager_id)
    assert manager is not None
    service = _service(session)
    review_case = service.create_case(
        manager,
        ScenarioKey(scenario_key),
        ScenarioVersion(1),
        f"M5.3 Case {uuid4()}",
        (
            {"area_code": "M53", "review_type": "routine"}
            if scenario_key == "process_review"
            else {"standard_reference": "ISO-9001", "scope_summary": "pilot"}
        ),
        occurred_at=NOW,
    )
    return ReviewCaseId(review_case.id)


def _user(engine: Engine, user_id: UserId) -> User:
    with Session(engine) as session:
        user = SqlAlchemyUserRepository(session).get(user_id)
        assert user is not None
        return user


def test_candidates_are_case_scoped_role_aware_and_fail_closed(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_fixture(postgres_engine)
    with Session(postgres_engine) as session, session.begin():
        case_id = _create_case(session, fixture, "process_review")
        manager = SqlAlchemyUserRepository(session).get(fixture.manager_id)
        non_manager = SqlAlchemyUserRepository(session).get(fixture.non_manager_id)
        admin = SqlAlchemyUserRepository(session).get(fixture.admin_id)
        assert manager is not None and non_manager is not None and admin is not None
        service = _service(session)

        candidates = service.list_case_member_candidates(
            manager,
            case_id,
            "lead",
            query=" candidate ",
            limit=20,
        )
        assert [candidate.id for candidate in candidates] == [fixture.candidate_id]
        assert all(
            candidate.id not in {fixture.inactive_id, fixture.foreign_user_id}
            for candidate in candidates
        )

        with pytest.raises(ReviewAuthorizationError):
            service.list_case_member_candidates(non_manager, case_id, "lead")
        with pytest.raises(ReviewAuthorizationError):
            service.list_case_member_candidates(admin, case_id, "lead")
        with pytest.raises(ValueError):
            service.list_case_member_candidates(manager, case_id, "not-a-role")


@pytest.mark.parametrize("scenario_key", ["process_review", "compliance_review"])
def test_add_remove_and_exact_role_validation_cover_both_scenarios(
    postgres_engine: Engine,
    scenario_key: str,
) -> None:
    fixture = _seed_fixture(postgres_engine, scenario_key=scenario_key)
    with Session(postgres_engine) as session, session.begin():
        case_id = _create_case(session, fixture, scenario_key)
        manager = SqlAlchemyUserRepository(session).get(fixture.manager_id)
        assert manager is not None
        coordinator = build_case_team_coordinator(session)
        added = coordinator.add_case_member_result(
            manager,
            case_id,
            fixture.candidate_id,
            "observer",
            occurred_at=NOW,
        )
        assert added.member.user_id == fixture.candidate_id
        removed = coordinator.remove_case_member_result(
            manager,
            case_id,
            fixture.candidate_id,
            "observer",
            occurred_at=NOW,
        )
        assert removed.member == added.member
        with pytest.raises(ValueError):
            coordinator.add_case_member_result(
                manager,
                case_id,
                fixture.candidate_id,
                "unknown",
            )

    with Session(postgres_engine) as verification:
        assert verification.scalar(
            select(func.count()).select_from(CaseMemberRecord).where(
                CaseMemberRecord.case_id == case_id,
                CaseMemberRecord.user_id == fixture.candidate_id,
            )
        ) == 0
        assert verification.scalar(
            select(func.count()).select_from(ActivityRecord).where(
                ActivityRecord.review_case_id == case_id,
                ActivityRecord.event_type == "review_case.member_removed",
                ActivityRecord.metadata_json["role_key"].as_string() == "observer",
            )
        ) == 1


def test_last_manager_uses_complete_roles_and_preserves_failed_remove(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_fixture(postgres_engine)
    with Session(postgres_engine) as session, session.begin():
        case_id = _create_case(session, fixture, "process_review")
        manager = SqlAlchemyUserRepository(session).get(fixture.manager_id)
        assert manager is not None
        coordinator = build_case_team_coordinator(session)
        coordinator.add_case_member_result(manager, case_id, fixture.manager_id, "observer")
        coordinator.remove_case_member_result(manager, case_id, fixture.manager_id, "observer")
        before = verification_counts(session, case_id)
        with pytest.raises(CaseManagerConflictError):
            coordinator.remove_case_member_result(manager, case_id, fixture.manager_id, "lead")
        assert verification_counts(session, case_id) == before


def verification_counts(session: Session, case_id: ReviewCaseId) -> tuple[int, int]:
    members = session.scalar(
        select(func.count())
        .select_from(CaseMemberRecord)
        .where(CaseMemberRecord.case_id == case_id)
    )
    activities = session.scalar(
        select(func.count()).select_from(ActivityRecord).where(
            ActivityRecord.review_case_id == case_id,
            ActivityRecord.event_type == "review_case.member_removed",
        )
    )
    return int(members or 0), int(activities or 0)


def _identity_client(engine: Engine, user_id: UserId) -> TestClient:
    user = _user(engine, user_id)
    app = create_app()

    def database_session() -> Iterator[Session]:
        with Session(engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def current_identity() -> CurrentIdentity:
        return CurrentIdentity(
            auth_session=AuthSession(
                id=AuthSessionId(uuid4()),
                organization_id=user.organization_id,
                user_id=user.id,
                token_hash="a" * 64,
                expires_at=NOW + timedelta(hours=1),
                created_at=NOW,
            ),
            user=user,
        )

    app.dependency_overrides[get_database_session] = database_session
    app.dependency_overrides[get_current_identity] = current_identity
    return TestClient(app, base_url="https://testserver")


def test_http_candidate_add_remove_and_unauthorized_name_boundary(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_fixture(postgres_engine)
    with Session(postgres_engine) as session, session.begin():
        case_id = _create_case(session, fixture, "process_review")

    manager_client = _identity_client(postgres_engine, fixture.manager_id)
    non_manager_client = _identity_client(postgres_engine, fixture.non_manager_id)
    case_path = f"/api/v1/review-cases/{case_id}"
    candidates = manager_client.get(
        f"{case_path}/member-candidates",
        params={"role_key": "observer", "q": "Candidate"},
    )
    assert candidates.status_code == 200
    assert candidates.json() == [
        {"user_id": str(fixture.candidate_id), "display_name": "Candidate User"}
    ]
    forbidden = non_manager_client.get(
        f"{case_path}/member-candidates",
        params={"role_key": "observer", "q": "Candidate"},
    )
    assert forbidden.status_code == 403
    assert "Candidate User" not in forbidden.text

    added = manager_client.post(
        f"{case_path}/members",
        json={"user_id": str(fixture.candidate_id), "role_key": "observer"},
    )
    assert added.status_code == 201
    removed = manager_client.delete(
        f"{case_path}/members/{fixture.candidate_id}",
        params={"role_key": "observer"},
    )
    assert removed.status_code == 200


def test_system_admin_needs_an_explicit_case_role_for_team_management(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_fixture(postgres_engine)
    with Session(postgres_engine) as session, session.begin():
        case_id = _create_case(session, fixture, "process_review")
        manager = SqlAlchemyUserRepository(session).get(fixture.manager_id)
        admin = SqlAlchemyUserRepository(session).get(fixture.admin_id)
        assert manager is not None and admin is not None
        service = _service(session)
        with pytest.raises(ReviewAuthorizationError):
            service.list_case_member_candidates(admin, case_id, "observer")
        build_case_team_coordinator(session).add_case_member_result(
            manager,
            case_id,
            fixture.admin_id,
            "lead",
        )
        candidates = service.list_case_member_candidates(admin, case_id, "observer")
        assert fixture.candidate_id in {candidate.id for candidate in candidates}


def _run_two_session_race(
    engine: Engine,
    first: Callable[[], object],
    second: Callable[[], object],
) -> list[str]:
    barrier = Barrier(2)

    def attempt(worker: Callable[[], object]) -> str:
        barrier.wait()
        try:
            worker()
        except ReviewAuthorizationError:
            return "403"
        except (CaseManagerConflictError, UserDeactivationConflictError):
            return "409"
        return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        return list(executor.map(attempt, (first, second)))


def _assert_case_has_effective_manager(
    engine: Engine,
    organization_id: OrganizationId,
    case_id: ReviewCaseId,
) -> None:
    with Session(engine) as session:
        repository = SqlAlchemyReviewCoreRepository(session)
        review_case = repository.get_case(organization_id, case_id)
        if review_case is None:
            return
        policy = build_scenario_registry().get(
            review_case.scenario_key,
            review_case.scenario_version,
        )
        users = SqlAlchemyUserRepository(session).list_for_organization(
            review_case.organization_id
        )
        assert effective_case_manager_ids(
            policy,
            repository.list_case_members(review_case.organization_id, case_id),
            users,
        )


def _assert_organization_cases_have_effective_managers(
    engine: Engine,
    organization_id: OrganizationId,
) -> None:
    with Session(engine) as session:
        repository = SqlAlchemyReviewCoreRepository(session)
        users = SqlAlchemyUserRepository(session).list_for_organization(organization_id)
        registry = build_scenario_registry()
        for review_case in repository.list_cases(organization_id):
            policy = registry.get(review_case.scenario_key, review_case.scenario_version)
            assert effective_case_manager_ids(
                policy,
                repository.list_case_members(organization_id, review_case.id),
                users,
            )


def test_concurrent_add_and_deactivation_preserve_a_manager(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_fixture(postgres_engine)
    with Session(postgres_engine) as session, session.begin():
        case_id = _create_case(session, fixture, "process_review")

    def add_member() -> object:
        with Session(postgres_engine) as session, session.begin():
            manager = SqlAlchemyUserRepository(session).get(fixture.manager_id)
            assert manager is not None
            return build_case_team_coordinator(session).add_case_member_result(
                manager,
                case_id,
                fixture.second_manager_id,
                "lead",
            )

    def deactivate_manager() -> object:
        with Session(postgres_engine) as session, session.begin():
            admin = SqlAlchemyUserRepository(session).get(fixture.admin_id)
            assert admin is not None
            return build_case_team_coordinator(session).update_user(
                admin,
                fixture.manager_id,
                is_active=False,
            )

    results = _run_two_session_race(postgres_engine, add_member, deactivate_manager)
    assert results.count("success") >= 1
    _assert_case_has_effective_manager(postgres_engine, fixture.organization_id, case_id)


def test_concurrent_create_and_deactivation_preserve_a_manager(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_fixture(postgres_engine)

    def create_case() -> object:
        with Session(postgres_engine) as session, session.begin():
            manager = SqlAlchemyUserRepository(session).get(fixture.manager_id)
            assert manager is not None
            return build_case_team_coordinator(session).create_case(
                manager,
                ScenarioKey("process_review"),
                ScenarioVersion(1),
                f"M5.3 Concurrent Case {uuid4()}",
                {"area_code": "M53", "review_type": "routine"},
                occurred_at=NOW,
            )

    def deactivate_manager() -> object:
        with Session(postgres_engine) as session, session.begin():
            admin = SqlAlchemyUserRepository(session).get(fixture.admin_id)
            assert admin is not None
            return build_case_team_coordinator(session).update_user(
                admin,
                fixture.manager_id,
                is_active=False,
            )

    results = _run_two_session_race(postgres_engine, create_case, deactivate_manager)
    assert results.count("success") >= 1
    _assert_organization_cases_have_effective_managers(
        postgres_engine,
        fixture.organization_id,
    )


def test_concurrent_remove_and_deactivation_preserve_a_manager(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_fixture(postgres_engine)
    with Session(postgres_engine) as session, session.begin():
        case_id = _create_case(session, fixture, "process_review")
        manager = SqlAlchemyUserRepository(session).get(fixture.manager_id)
        assert manager is not None
        build_case_team_coordinator(session).add_case_member_result(
            manager,
            case_id,
            fixture.second_manager_id,
            "lead",
        )

    def remove_second_manager() -> object:
        with Session(postgres_engine) as session, session.begin():
            manager = SqlAlchemyUserRepository(session).get(fixture.manager_id)
            assert manager is not None
            return build_case_team_coordinator(session).remove_case_member_result(
                manager,
                case_id,
                fixture.second_manager_id,
                "lead",
            )

    def deactivate_manager() -> object:
        with Session(postgres_engine) as session, session.begin():
            admin = SqlAlchemyUserRepository(session).get(fixture.admin_id)
            assert admin is not None
            return build_case_team_coordinator(session).update_user(
                admin,
                fixture.manager_id,
                is_active=False,
            )

    results = _run_two_session_race(postgres_engine, remove_second_manager, deactivate_manager)
    assert results.count("success") >= 1
    _assert_case_has_effective_manager(postgres_engine, fixture.organization_id, case_id)


def test_failed_deactivation_is_atomic_and_keeps_sessions_and_audit_unchanged(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_fixture(postgres_engine)
    with Session(postgres_engine) as session, session.begin():
        case_id = _create_case(session, fixture, "process_review")
        session.add(
            AuthSessionRecord(
                id=uuid4(),
                organization_id=fixture.organization_id,
                user_id=fixture.manager_id,
                token_hash=uuid4().hex + uuid4().hex,
                expires_at=NOW + timedelta(hours=1),
                created_at=NOW,
            )
        )
        before_audit = session.scalar(
            select(func.count()).select_from(PlatformAuditEventRecord).where(
                PlatformAuditEventRecord.target_user_id == fixture.manager_id,
                PlatformAuditEventRecord.event_type == "admin.user_updated",
            )
        )
        admin = SqlAlchemyUserRepository(session).get(fixture.admin_id)
        assert admin is not None
        with pytest.raises(UserDeactivationConflictError):
            build_case_team_coordinator(session).update_user(
                admin,
                fixture.manager_id,
                is_active=False,
                now=NOW,
            )
        manager = SqlAlchemyUserRepository(session).get(fixture.manager_id)
        assert manager is not None and manager.is_active
        assert session.scalar(
            select(func.count()).select_from(PlatformAuditEventRecord).where(
                PlatformAuditEventRecord.target_user_id == fixture.manager_id,
                PlatformAuditEventRecord.event_type == "admin.user_updated",
            )
        ) == before_audit
        session.expire_all()
        session_record = session.scalar(
            select(AuthSessionRecord).where(AuthSessionRecord.user_id == fixture.manager_id)
        )
        assert session_record is not None and session_record.revoked_at is None
        assert session.scalar(
            select(func.count()).select_from(CaseMemberRecord).where(
                CaseMemberRecord.case_id == case_id
            )
        ) == 1

    admin_client = _identity_client(postgres_engine, fixture.admin_id)
    response = admin_client.patch(
        f"/api/v1/admin/users/{fixture.manager_id}",
        json={"is_active": False},
    )
    assert response.status_code == 409
    with Session(postgres_engine) as verification:
        manager = SqlAlchemyUserRepository(verification).get(fixture.manager_id)
        assert manager is not None and manager.is_active
        session_record = verification.scalar(
            select(AuthSessionRecord).where(AuthSessionRecord.user_id == fixture.manager_id)
        )
        assert session_record is not None and session_record.revoked_at is None
        assert verification.scalar(
            select(func.count()).select_from(PlatformAuditEventRecord).where(
                PlatformAuditEventRecord.target_user_id == fixture.manager_id,
                PlatformAuditEventRecord.event_type == "admin.user_updated",
            )
        ) == 0
        assert verification.scalar(
            select(func.count()).select_from(CaseMemberRecord).where(
                CaseMemberRecord.case_id == case_id
            )
        ) == 1
        assert verification.scalar(
            select(func.count()).select_from(ActivityRecord).where(
                ActivityRecord.review_case_id == case_id,
            )
        ) == 1


def test_concurrent_final_manager_removal_has_one_success_and_no_zero_manager_case(
    postgres_engine: Engine,
) -> None:
    fixture = _seed_fixture(postgres_engine)
    with Session(postgres_engine) as session, session.begin():
        case_id = _create_case(session, fixture, "process_review")
        manager = SqlAlchemyUserRepository(session).get(fixture.manager_id)
        assert manager is not None
        coordinator = build_case_team_coordinator(session)
        coordinator.add_case_member_result(manager, case_id, fixture.second_manager_id, "lead")

    barrier = Barrier(2)

    def attempt(actor_id: UserId, target_id: UserId) -> str:
        with Session(postgres_engine) as session, session.begin():
            actor = SqlAlchemyUserRepository(session).get(actor_id)
            assert actor is not None
            barrier.wait()
            try:
                build_case_team_coordinator(session).remove_case_member_result(
                    actor,
                    case_id,
                    target_id,
                    "lead",
                )
            except ReviewAuthorizationError:
                return "403"
            except CaseManagerConflictError:
                return "409"
            return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda pair: attempt(*pair),
                (
                    (fixture.manager_id, fixture.second_manager_id),
                    (fixture.second_manager_id, fixture.manager_id),
                ),
            )
        )
    assert results.count("success") == 1
    assert results.count("403") + results.count("409") == 1
    with Session(postgres_engine) as verification:
        remaining = verification.scalar(
            select(func.count()).select_from(CaseMemberRecord).where(
                CaseMemberRecord.case_id == case_id,
                CaseMemberRecord.role_key == "lead",
            )
        )
        assert remaining == 1
