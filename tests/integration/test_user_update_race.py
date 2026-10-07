"""Concurrent admin PATCHes on one User keep each other's fields (issue #87 B3).

Every PATCH in these tests runs through `CaseTeamUserCoordinator.update_user`, the same entry
point the API uses. A hook in the repository's `update` makes the interleaving deterministic: each
transaction's first user write waits (bounded) for the other transaction to arrive. Without an
Organization lock plus a locked re-read both transactions decide from the same old snapshot, both
write and both commit; with it the second PATCH blocks before it reads, so the wait times out,
the first commits and the second decides from the committed row.
"""

import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from os import environ
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from easyaudit_next.composition import build_case_team_coordinator
from easyaudit_next.platform.application.administration import LastSystemAdminError
from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import PlatformRole, User
from easyaudit_next.platform.persistence.models import (
    DepartmentRecord,
    OrganizationRecord,
    UserRecord,
)
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository

pytestmark = pytest.mark.skipif(
    environ.get("EASYAUDIT_RUN_POSTGRES_TESTS") != "1",
    reason="PostgreSQL integration tests are opt-in outside CI",
)

RENDEZVOUS_SECONDS = 1.5


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


def _user(organization_id: UUID, user_id: UUID, role: PlatformRole) -> User:
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
        [_user(organization_id, admin_id, PlatformRole.SYSTEM_ADMIN) for admin_id in admin_ids],
        target_id,
        department_ids,
    )


class _Rendezvous:
    """Make each transaction's first user write wait (bounded) for the other's."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.both_arrived = threading.Event()
        self._arrived: set[int] = set()
        self._lock = threading.Lock()
        original = SqlAlchemyUserRepository.update

        def update(repo: SqlAlchemyUserRepository, user: Any) -> None:
            transaction = id(repo._session)  # one Session == one transaction
            with self._lock:
                first = transaction not in self._arrived
                self._arrived.add(transaction)
                if len(self._arrived) >= 2:
                    self.both_arrived.set()
            if first:
                self.both_arrived.wait(RENDEZVOUS_SECONDS)
            original(repo, user)

        monkeypatch.setattr(SqlAlchemyUserRepository, "update", update)


_returned: dict[tuple[UUID, str], User] = {}


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
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = _seed(engine)
    admin = seed.admins[0]
    _Rendezvous(monkeypatch)

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
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = _seed(engine)
    admin = seed.admins[0]
    _Rendezvous(monkeypatch)

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
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = _seed(engine)
    admin = seed.admins[0]
    _Rendezvous(monkeypatch)

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
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = _seed(engine)
    actor, victim = seed.admins
    _Rendezvous(monkeypatch)

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
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = _seed(engine)
    a, b = seed.admins
    _Rendezvous(monkeypatch)

    results = _race(
        [
            lambda: _patch(engine, a, b.id, is_active=False),
            lambda: _patch(engine, b, a.id, platform_role=PlatformRole.ORDINARY_USER),
        ]
    )

    _assert_one_loser_and_an_admin_left(engine, results, a, b)


def test_last_admin_survives_two_deactivations(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = _seed(engine)
    a, b = seed.admins
    _Rendezvous(monkeypatch)

    results = _race(
        [
            lambda: _patch(engine, a, b.id, is_active=False),
            lambda: _patch(engine, b, a.id, is_active=False),
        ]
    )

    _assert_one_loser_and_an_admin_left(engine, results, a, b)


def test_promotion_racing_deactivation_of_the_same_user_is_checked_against_the_new_role(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The target is promoted while the other PATCH deactivates it from a pre-promotion read.

    Admins: A (actor) and the target T, promoted to system_admin by one PATCH while another
    deactivates T. Either order is fine, but A is then the only admin, so A must not be demotable
    by T's stale authority: afterwards at least one active system_admin exists.
    """

    seed = _seed(engine, admin_count=1)
    (a,) = seed.admins
    _Rendezvous(monkeypatch)

    results = _race(
        [
            lambda: _patch(engine, a, seed.target_id, platform_role=PlatformRole.SYSTEM_ADMIN),
            lambda: _patch(engine, a, seed.target_id, is_active=False),
        ]
    )

    assert results == ["ok", "ok"]
    row = _row(engine, seed.target_id)
    assert row.platform_role == "system_admin" and row.is_active is False
    assert _row(engine, a.id).is_active is True


def test_response_reflects_the_committed_row_not_the_pre_lock_read(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rename racing a deactivation must not report (or audit) the target as still active."""

    seed = _seed(engine)
    admin = seed.admins[0]
    _Rendezvous(monkeypatch)

    results = _race(
        [
            lambda: _patch(engine, admin, seed.target_id, is_active=False),
            lambda: _patch(engine, admin, seed.target_id, display_name="Renamed"),
        ]
    )

    assert results == ["ok", "ok"]
    row = _row(engine, seed.target_id)
    assert (row.display_name, row.is_active) == ("Renamed", False)
    renamed = _returned[(seed.target_id, "display_name")]
    deactivated = _returned[(seed.target_id, "is_active")]
    # Whichever PATCH ran second saw the first one's committed change.
    assert (renamed.display_name, deactivated.is_active) == ("Renamed", False)
    assert renamed.is_active is False or deactivated.display_name == "Renamed"


@pytest.mark.parametrize("change", ["demoted", "deactivated"])
def test_actor_authority_is_checked_against_the_locked_row(engine: Engine, change: str) -> None:
    """The actor object comes from before the lock; a committed demotion/deactivation wins."""

    seed = _seed(engine)
    a, b = seed.admins
    stale_b = b  # what the request authenticated with
    with Session(engine) as session, session.begin():
        record = session.get(UserRecord, b.id)
        assert record is not None
        if change == "demoted":
            record.platform_role = "ordinary_user"
        else:
            record.is_active = False

    assert (
        _patch(engine, stale_b, seed.target_id, display_name="By stale admin") == "PermissionError"
    )
    assert _row(engine, seed.target_id).display_name == "B3 target"
    assert a.id != b.id
