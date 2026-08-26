from uuid import uuid4

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from easyaudit_next.composition import build_scenario_registry
from easyaudit_next.platform.domain.ids import OrganizationId, UserId
from easyaudit_next.platform.persistence.models import OrganizationRecord, UserRecord
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.application.review_planning import ReviewAuthorizationError
from easyaudit_next.review_core.application.review_verification import VerificationClosureService
from easyaudit_next.review_core.persistence.verification_repositories import (
    SqlAlchemyVerificationClosureRepository,
)
from tests.integration.test_review_verification_semantics import NOW, _seed_case


def test_system_admin_without_scenario_relationship_is_not_a_reviewer(
    postgres_engine: Engine,
) -> None:
    _, _, finding_id, _, _, unrelated_id = _seed_case(
        postgres_engine,
        finding_lifecycle="verifying",
        include_unrelated=True,
    )
    assert unrelated_id is not None

    with Session(postgres_engine) as setup, setup.begin():
        record = setup.get(UserRecord, unrelated_id)
        assert record is not None
        record.platform_role = "system_admin"

    with Session(postgres_engine, expire_on_commit=False) as session:
        admin = SqlAlchemyUserRepository(session).get(unrelated_id)
        assert admin is not None
        service = VerificationClosureService(
            SqlAlchemyVerificationClosureRepository(session),
            build_scenario_registry(),
        )
        with pytest.raises(ReviewAuthorizationError, match="not visible"):
            service.submit_verification(
                admin,
                finding_id,
                "approve",
                {"result": "approved"},
                occurred_at=NOW,
            )
        session.rollback()


def test_cross_organization_user_cannot_resolve_verification_target(
    postgres_engine: Engine,
) -> None:
    _, _, finding_id, _, _, _ = _seed_case(
        postgres_engine,
        finding_lifecycle="verifying",
    )
    other_organization_id = OrganizationId(uuid4())
    other_user_id = UserId(uuid4())

    with Session(postgres_engine) as setup, setup.begin():
        setup.add(
            OrganizationRecord(
                id=other_organization_id,
                name=f"M2.5 isolation {other_organization_id}",
            )
        )
        setup.flush()
        setup.add(
            UserRecord(
                id=other_user_id,
                organization_id=other_organization_id,
                display_name="Cross Organization User",
                platform_role="ordinary_user",
            )
        )

    with Session(postgres_engine, expire_on_commit=False) as session:
        outsider = SqlAlchemyUserRepository(session).get(other_user_id)
        assert outsider is not None
        service = VerificationClosureService(
            SqlAlchemyVerificationClosureRepository(session),
            build_scenario_registry(),
        )
        with pytest.raises(LookupError, match="Finding not found"):
            service.submit_verification(
                outsider,
                finding_id,
                "approve",
                {"result": "approved"},
                occurred_at=NOW,
            )
        session.rollback()
