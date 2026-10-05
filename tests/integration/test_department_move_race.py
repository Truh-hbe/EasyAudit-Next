"""Concurrent department moves must never commit a cycle (issue #86 B1).

Both transactions pass the ancestor check against the old tree. The hook in the repository's
UPDATE makes the interleaving deterministic: the first writer waits (bounded) for the other to
arrive. Without an organization-level lock both arrive, both UPDATE and both COMMIT, leaving
A -> B -> A. With the lock the second move blocks before its check, the wait times out, the first
commits, and the second re-checks against the new tree and is rejected.
"""

import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from os import environ
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from easyaudit_next.composition import build_platform_administration_service
from easyaudit_next.platform.application.services import DepartmentCycleError
from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId
from easyaudit_next.platform.domain.models import PlatformRole, User
from easyaudit_next.platform.persistence.models import (
    DepartmentRecord,
    OrganizationRecord,
    UserRecord,
)
from easyaudit_next.platform.persistence.repositories import SqlAlchemyDepartmentRepository

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


def _seed(engine: Engine, department_count: int = 2) -> tuple[User, list[UUID]]:
    organization_id = uuid4()
    admin_id = uuid4()
    department_ids = [uuid4() for _ in range(department_count)]
    with Session(engine) as session, session.begin():
        session.add(OrganizationRecord(id=organization_id, name=f"B1 {organization_id}"))
        session.flush()
        session.add(
            UserRecord(
                id=admin_id,
                organization_id=organization_id,
                display_name="B1 Admin",
                platform_role="system_admin",
            )
        )
        for index, department_id in enumerate(department_ids):
            session.add(
                DepartmentRecord(
                    id=department_id,
                    organization_id=organization_id,
                    name=f"D{index}",
                )
            )
    admin = User(
        id=UserId(admin_id),
        organization_id=OrganizationId(organization_id),
        display_name="B1 Admin",
        platform_role=PlatformRole.SYSTEM_ADMIN,
    )
    return admin, department_ids


class _Rendezvous:
    """Let each transaction's first UPDATE wait (bounded) for the other transaction's.

    Only the first `update` per transaction counts (one admin move calls `update` twice), and
    each `_move` runs in its own thread, so the thread id identifies the transaction.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch, expected: int = 2) -> None:
        self.both_arrived = threading.Event()
        self._arrived: set[int] = set()
        self._lock = threading.Lock()
        self._expected = expected
        original = SqlAlchemyDepartmentRepository.update

        def update(repo: SqlAlchemyDepartmentRepository, department: Any) -> None:
            transaction = threading.get_ident()
            with self._lock:
                first = transaction not in self._arrived
                self._arrived.add(transaction)
                if len(self._arrived) >= self._expected:
                    self.both_arrived.set()
            if first:
                self.both_arrived.wait(RENDEZVOUS_SECONDS)
            original(repo, department)

        monkeypatch.setattr(SqlAlchemyDepartmentRepository, "update", update)


def _move(engine: Engine, admin: User, department_id: UUID, parent_id: UUID | None) -> str:
    """Run one admin move in its own transaction; return 'moved' or 'cycle'."""

    with Session(engine) as session:
        try:
            build_platform_administration_service(session).update_department(
                admin,
                DepartmentId(department_id),
                parent_id=DepartmentId(parent_id) if parent_id else None,
                set_parent=True,
            )
            session.commit()
            return "moved"
        except DepartmentCycleError:
            session.rollback()
            return "cycle"


def _parents(engine: Engine, ids: list[UUID]) -> dict[UUID, UUID | None]:
    with Session(engine) as session:
        rows = session.execute(
            select(DepartmentRecord.id, DepartmentRecord.parent_id).where(
                DepartmentRecord.id.in_(ids)
            )
        )
        return {row.id: row.parent_id for row in rows}


def _race(pairs: list[Callable[[], str]]) -> list[str]:
    with ThreadPoolExecutor(max_workers=len(pairs)) as pool:
        futures = [pool.submit(call) for call in pairs]
        return [future.result(timeout=30) for future in futures]


def test_opposite_moves_commit_at_most_one_and_never_a_cycle(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, (a, b) = _seed(engine)
    _Rendezvous(monkeypatch)

    results = _race([lambda: _move(engine, admin, a, b), lambda: _move(engine, admin, b, a)])

    assert sorted(results) == ["cycle", "moved"]
    parents = _parents(engine, [a, b])
    assert sum(parent is not None for parent in parents.values()) == 1


def test_unrelated_moves_in_one_organization_both_succeed(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, (a, b, c, d) = _seed(engine, 4)
    _Rendezvous(monkeypatch)

    results = _race([lambda: _move(engine, admin, a, b), lambda: _move(engine, admin, c, d)])

    assert results == ["moved", "moved"]
    parents = _parents(engine, [a, b, c, d])
    assert parents[a] == b and parents[c] == d


def test_moves_in_different_organizations_do_not_block_each_other(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_1, (a1, b1) = _seed(engine)
    admin_2, (a2, b2) = _seed(engine)
    rendezvous = _Rendezvous(monkeypatch)

    started = time.monotonic()
    results = _race(
        [lambda: _move(engine, admin_1, a1, b1), lambda: _move(engine, admin_2, a2, b2)]
    )
    elapsed = time.monotonic() - started

    assert results == ["moved", "moved"]
    # Two distinct transactions reached their UPDATE together and nobody sat out the rendezvous
    # timeout: a global (cross-organization) lock would make one wait RENDEZVOUS_SECONDS.
    assert rendezvous.both_arrived.is_set()
    assert elapsed < RENDEZVOUS_SECONDS * 0.6
