import pytest
from sqlalchemy import Engine, delete, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from easyaudit_next.composition import build_scenario_registry
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.application.review_verification import VerificationClosureService
from easyaudit_next.review_core.persistence.models import SubmissionRecord
from easyaudit_next.review_core.persistence.verification_repositories import (
    SqlAlchemyVerificationClosureRepository,
)
from tests.integration.test_review_verification_semantics import (
    NOW,
    _seed_case,
    postgres_engine,
)

__all__ = ["postgres_engine"]


def test_verification_submission_rejects_update_and_delete_in_postgresql(
    postgres_engine: Engine,
) -> None:
    _, _, finding_id, _, reviewer_id, _ = _seed_case(
        postgres_engine,
        finding_lifecycle="verifying",
    )

    with Session(postgres_engine, expire_on_commit=False) as session:
        reviewer = SqlAlchemyUserRepository(session).get(reviewer_id)
        assert reviewer is not None
        service = VerificationClosureService(
            SqlAlchemyVerificationClosureRepository(session),
            build_scenario_registry(),
            SqlAlchemyUserRepository(session),
        )
        submission, _ = service.submit_verification(
            reviewer,
            finding_id,
            "approve",
            {"result": "approved", "comment": "Immutable verification"},
            occurred_at=NOW,
        )
        session.commit()

    with Session(postgres_engine) as mutation:
        with pytest.raises(DBAPIError, match="append-only"):
            mutation.execute(
                update(SubmissionRecord)
                .where(SubmissionRecord.id == submission.id)
                .values(payload_json={"tampered": True})
            )
            mutation.flush()
        mutation.rollback()

    with Session(postgres_engine) as mutation:
        with pytest.raises(DBAPIError, match="append-only"):
            mutation.execute(
                delete(SubmissionRecord).where(SubmissionRecord.id == submission.id)
            )
            mutation.flush()
        mutation.rollback()

    with Session(postgres_engine) as verification:
        persisted = verification.scalar(
            select(SubmissionRecord).where(SubmissionRecord.id == submission.id)
        )
        assert persisted is not None
        assert persisted.purpose == "verification"
