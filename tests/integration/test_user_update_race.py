"""Concurrent admin PATCHes on one User keep each other's fields (issue #87 B3).

Every PATCH in these tests runs through `CaseTeamUserCoordinator.update_user`, the same entry
point the API uses. A hook on the Organization lock makes the interleaving deterministic: each
transaction waits at its first lock attempt until the other has arrived, so both PATCHes are in
flight (and hold pre-lock snapshots of the actor) before either one proceeds. One then takes the
lock and commits while the other blocks, and must decide from the committed rows. The tests with a
pre-loaded Session cover the identity-map side: a row loaded earlier in the same Session must not
be what the decision is made from.
"""

import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from os import environ
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from easyaudit_next.composition import (
    build_case_team_coordinator,
    build_platform_administration_service,
)
from easyaudit_next.platform.application.administration import LastSystemAdminError
from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import PlatformRole, User
from easyaudit_next.platform.persistence.models import (
    DepartmentRecord,
    OrganizationRecord,
    PlatformAuditEventRecord,
    UserRecord,
)
from easyaudit_next.platform.persistence.repositories import (
    SqlAlchemyOrganizationRepository,
)
from tests.integration.barrier_support import CountingBarrier
from tests.integration.test_m5_3_case_team_management import _create_case, _seed_fixture, _user

pytestmark = pytest.mark.skipif(
    environ.get("EASYAUDIT_RUN_POSTGRES_TESTS") != "1",
    reason="PostgreSQL integration tests are opt-in outside CI",
)

RENDEZVOUS_SECONDS = 10.0


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    engine = create_engine(environ["DATABASE_URL"], pool_pre_ping=True, pool_size=10)
    yield engine
    engine.dispose()


@dataclass
class Seed:
    organization_id: UUID
    admins: list[User]
    target_id: UUID
    department_ids: list[UUID]


def _make_user(organization_id: UUID, user_id: UUID, role: PlatformRole) -> User:
    return User(
        id=UserId(user_id),
        organization_id=OrganizationId(organization_id),
        display_name="B3 user",
        platform_role=role,
    )


def _seed(engine: Engine, admin_count: int = 2) -> Seed:
    organization_id = uuid4()
    admin_ids = [uuid4() for _ in range(admin_count)]
    target_id = uuid4()
    department_ids = [uuid4(), uuid4()]
    with Session(engine) as session, session.begin():
        session.add(OrganizationRecord(id=organization_id, name=f"B3 {organization_id}"))
        session.flush()
        for department_id in department_ids:
            session.add(
                DepartmentRecord(
                    id=department_id, organization_id=organization_id, name=str(department_id)
                )
            )
        session.flush()
        for admin_id in admin_ids:
            session.add(
                UserRecord(
                    id=admin_id,
                    organization_id=organization_id,
                    display_name="B3 admin",
                    platform_role="system_admin",
                )
            )
        session.add(
            UserRecord(
                id=target_id,
                organization_id=organization_id,
                display_name="B3 target",
                platform_role="ordinary_user",
            )
        )
    return Seed(
        organization_id,
        [
            _make_user(organization_id, admin_id, PlatformRole.SYSTEM_ADMIN)
            for admin_id in admin_ids
        ],
        target_id,
        department_ids,
    )


class _Rendezvous:
    """Hold each transaction at its first Organization lock attempt until both have arrived."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.barrier = CountingBarrier(2)
        self._seen: set[int] = set()
        self._lock = threading.Lock()
        original = SqlAlchemyOrganizationRepository.lock_for_update

        def lock_for_update(repo: SqlAlchemyOrganizationRepository, organization_id: Any) -> Any:
            transaction = id(repo._session)  # one Session == one transaction
            with self._lock:
                first = transaction not in self._seen
                self._seen.add(transaction)
            if first:
                self.barrier.wait(RENDEZVOUS_SECONDS)
            return original(repo, organization_id)

        monkeypatch.setattr(SqlAlchemyOrganizationRepository, "lock_for_update", lock_for_update)

    def assert_both_arrived(self) -> None:
        assert self.barrier.hits == 2


_returned: dict[tuple[UUID, str], User] = {}


@pytest.fixture
def rendezvous(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Rendezvous]:
    rendezvous = _Rendezvous(monkeypatch)
    yield rendezvous
    # If the hook stops being reached the barrier never trips and the race would be vacuous.
    rendezvous.assert_both_arrived()


def _patch(engine: Engine, actor: User, user_id: UUID, **fields: Any) -> str:
    """Run one PATCH in its own transaction; return 'ok' or the error class name.

    The returned user is kept in `_returned` under (user_id, first field name).
    """

    with Session(engine) as session:
        try:
            user = build_case_team_coordinator(session).update_user(
                actor, UserId(user_id), **fields
            )
            session.commit()
            _returned[(user_id, next(iter(fields)))] = user
            return "ok"
        except (LastSystemAdminError, PermissionError) as error:
            session.rollback()
            return type(error).__name__


def _race(calls: list[Callable[[], str]]) -> list[str]:
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(call) for call in calls]
        return [future.result(timeout=30) for future in futures]


def _row(engine: Engine, user_id: UUID) -> UserRecord:
    with Session(engine) as session:
        record = session.get(UserRecord, user_id)
        assert record is not None
        session.expunge(record)
        return record


def _assert_one_loser_and_an_admin_left(
    engine: Engine, results: list[str], a: User, b: User
) -> None:
    # The loser is refused either by the last-admin guard or, when the winner already removed
    # the loser's own admin rights, by the lock-time actor check.
    assert sorted(results) in (["LastSystemAdminError", "ok"], ["PermissionError", "ok"])
    rows = [_row(engine, user.id) for user in (a, b)]
    assert sum(row.is_active and row.platform_role == "system_admin" for row in rows) == 1


def test_deactivate_and_role_change_keep_both(
    engine: Engine, rendezvous: _Rendezvous
) -> None:
    seed = _seed(engine)
    admin = seed.admins[0]

    results = _race(
        [
            lambda: _patch(engine, admin, seed.target_id, is_active=False),
            lambda: _patch(engine, admin, seed.target_id, platform_role=PlatformRole.SYSTEM_ADMIN),
        ]
    )

    assert results == ["ok", "ok"]
    row = _row(engine, seed.target_id)
    assert row.is_active is False
    assert row.platform_role == "system_admin"


def test_deactivate_and_department_change_keep_both(
    engine: Engine, rendezvous: _Rendezvous
) -> None:
    seed = _seed(engine)
    admin = seed.admins[0]

    results = _race(
        [
            lambda: _patch(engine, admin, seed.target_id, is_active=False),
            lambda: _patch(
                engine,
                admin,
                seed.target_id,
                primary_department_id=DepartmentId(seed.department_ids[0]),
                set_primary_department=True,
            ),
        ]
    )

    assert results == ["ok", "ok"]
    row = _row(engine, seed.target_id)
    assert row.is_active is False
    assert row.primary_department_id == seed.department_ids[0]


def test_role_and_department_change_keep_both(
    engine: Engine, rendezvous: _Rendezvous
) -> None:
    seed = _seed(engine)
    admin = seed.admins[0]

    results = _race(
        [
            lambda: _patch(engine, admin, seed.target_id, platform_role=PlatformRole.SYSTEM_ADMIN),
            lambda: _patch(
                engine,
                admin,
                seed.target_id,
                primary_department_id=DepartmentId(seed.department_ids[1]),
                set_primary_department=True,
            ),
        ]
    )

    assert results == ["ok", "ok"]
    row = _row(engine, seed.target_id)
    assert row.platform_role == "system_admin"
    assert row.primary_department_id == seed.department_ids[1]


def test_display_name_and_deactivate_of_an_admin_keep_both(
    engine: Engine, rendezvous: _Rendezvous
) -> None:
    seed = _seed(engine)
    actor, victim = seed.admins

    results = _race(
        [
            lambda: _patch(engine, actor, victim.id, display_name="Renamed"),
            lambda: _patch(engine, actor, victim.id, is_active=False),
        ]
    )

    assert results == ["ok", "ok"]
    row = _row(engine, victim.id)
    assert row.display_name == "Renamed"
    assert row.is_active is False


def test_last_admin_survives_opposite_deactivate_and_demote(
    engine: Engine, rendezvous: _Rendezvous
) -> None:
    seed = _seed(engine)
    a, b = seed.admins

    results = _race(
        [
            lambda: _patch(engine, a, b.id, is_active=False),
            lambda: _patch(engine, b, a.id, platform_role=PlatformRole.ORDINARY_USER),
        ]
    )

    _assert_one_loser_and_an_admin_left(engine, results, a, b)


def test_last_admin_survives_two_deactivations(
    engine: Engine, rendezvous: _Rendezvous
) -> None:
    seed = _seed(engine)
    a, b = seed.admins

    results = _race(
        [
            lambda: _patch(engine, a, b.id, is_active=False),
            lambda: _patch(engine, b, a.id, is_active=False),
        ]
    )

    _assert_one_loser_and_an_admin_left(engine, results, a, b)


def _commit(engine: Engine, user_id: UUID, **columns: Any) -> None:
    with Session(engine) as session, session.begin():
        record = session.get(UserRecord, user_id)
        assert record is not None
        for name, value in columns.items():
            setattr(record, name, value)


def test_deactivation_from_a_stale_snapshot_cannot_remove_the_only_admin(engine: Engine) -> None:
    """T becomes the only active admin while the deactivation still holds T as ordinary_user.

    The Session already holds T's row (ordinary_user) in its identity map; another transaction
    promotes T and demotes the original admin. The deactivation must decide from the locked row.
    """

    seed = _seed(engine, admin_count=1)
    (original_admin,) = seed.admins
    promoted = _make_user(seed.organization_id, seed.target_id, PlatformRole.SYSTEM_ADMIN)

    with Session(engine) as session:
        stale = session.get(UserRecord, seed.target_id)
        assert stale is not None and stale.platform_role == "ordinary_user"
        _commit(engine, seed.target_id, platform_role="system_admin")
        _commit(engine, original_admin.id, platform_role="ordinary_user")
        with pytest.raises(LastSystemAdminError):
            build_platform_administration_service(session).update_user(
                promoted, UserId(seed.target_id), is_active=False
            )
        session.rollback()

    row = _row(engine, seed.target_id)
    assert row.is_active is True and row.platform_role == "system_admin"


@pytest.mark.parametrize("change", ["demoted", "deactivated"])
def test_actor_authority_is_checked_against_the_locked_row(engine: Engine, change: str) -> None:
    """The Session holds the actor's old row; a committed demotion/deactivation must win."""

    seed = _seed(engine)
    _, b = seed.admins

    with Session(engine) as session:
        preloaded = session.get(UserRecord, b.id)  # keep a strong ref: the map is weak
        assert preloaded is not None and preloaded.platform_role == "system_admin"
        if change == "demoted":
            _commit(engine, b.id, platform_role="ordinary_user")
        else:
            _commit(engine, b.id, is_active=False)
        with pytest.raises(PermissionError):
            build_case_team_coordinator(session).update_user(
                b, UserId(seed.target_id), display_name="By stale admin"
            )
        session.rollback()

    assert _row(engine, seed.target_id).display_name == "B3 target"


def test_response_and_audit_reflect_the_committed_row_not_the_pre_lock_read(
    engine: Engine, rendezvous: _Rendezvous
) -> None:
    """A rename racing a deactivation must not report (or audit) the target as still active."""

    seed = _seed(engine)
    admin = seed.admins[0]

    results = _race(
        [
            lambda: _patch(engine, admin, seed.target_id, is_active=False),
            lambda: _patch(engine, admin, seed.target_id, display_name="Renamed"),
        ]
    )

    assert results == ["ok", "ok"]
    row = _row(engine, seed.target_id)
    assert (row.display_name, row.is_active) == ("Renamed", False)
    # Whichever PATCH ran second saw the first one's committed change, in its response too.
    renamed = _returned[(seed.target_id, "display_name")]
    deactivated = _returned[(seed.target_id, "is_active")]
    assert renamed.is_active is False or deactivated.display_name == "Renamed"
    with Session(engine) as session:
        events = session.scalars(
            select(PlatformAuditEventRecord)
            .where(PlatformAuditEventRecord.target_user_id == seed.target_id)
            .order_by(PlatformAuditEventRecord.occurred_at)
        ).all()
    assert len(events) == 2
    assert events[-1].metadata_json["is_active"] is False


def test_deactivation_by_a_revoked_admin_is_forbidden_before_any_case_fact_is_visible(
    engine: Engine,
) -> None:
    """A revoked admin gets 403, not the 409 that discloses the target is a Case's only manager.

    B's request was authorized with a pre-demotion actor and then waited for the Organization
    lock; by the time it runs, B's demotion has committed.
    """

    fixture = _seed_fixture(engine)
    with Session(engine) as session, session.begin():
        _create_case(session, fixture, "process_review")
    stale_admin = _user(engine, fixture.admin_id)
    _commit(engine, fixture.admin_id, platform_role="ordinary_user")

    with Session(engine) as session, pytest.raises(PermissionError):
        build_case_team_coordinator(session).update_user(
            stale_admin, fixture.manager_id, is_active=False
        )
