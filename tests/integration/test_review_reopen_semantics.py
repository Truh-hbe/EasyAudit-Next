import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from easyaudit_next.composition import build_scenario_registry
from easyaudit_next.platform.persistence.repositories import SqlAlchemyUserRepository
from easyaudit_next.review_core.application.review_verification import VerificationClosureService
from easyaudit_next.review_core.persistence.models import (
    ActivityRecord,
    FindingRecord,
    SubmissionRecord,
)
from easyaudit_next.review_core.persistence.verification_repositories import (
    SqlAlchemyVerificationClosureRepository,
)
from tests.integration.test_review_verification_semantics import (
    NOW,
    _planning_service,
    _seed_case,
    postgres_engine,
)

__all__ = ["postgres_engine"]


def test_reopen_closed_finding_returns_to_rectifying_without_submission(
    postgres_engine: Engine,
) -> None:
    organization_id, _, finding_id, lead_id, _, _ = _seed_case(
        postgres_engine,
        finding_lifecycle="closed",
    )

    with Session(postgres_engine, expire_on_commit=False) as session:
        lead = SqlAlchemyUserRepository(session).get(lead_id)
        assert lead is not None
        service = VerificationClosureService(
            SqlAlchemyVerificationClosureRepository(session),
            build_scenario_registry(),
        )
        reopened = service.reopen_finding(
            lead,
            finding_id,
            reason="A later check invalidated the verification result",
            occurred_at=NOW,
        )
        session.commit()

    assert reopened.lifecycle.value == "rectifying"
    with Session(postgres_engine) as verification:
        assert verification.scalar(
            select(FindingRecord.lifecycle).where(FindingRecord.id == finding_id)
        ) == "rectifying"
        assert verification.scalar(
            select(func.count())
            .select_from(ActivityRecord)
            .where(
                ActivityRecord.organization_id == organization_id,
                ActivityRecord.finding_id == finding_id,
                ActivityRecord.event_type == "finding.reopened",
            )
        ) == 1
        assert verification.scalar(
            select(func.count())
            .select_from(SubmissionRecord)
            .where(
                SubmissionRecord.organization_id == organization_id,
                SubmissionRecord.finding_id == finding_id,
                SubmissionRecord.purpose == "verification",
            )
        ) == 0


def test_reopen_requires_non_blank_reason(postgres_engine: Engine) -> None:
    _, _, finding_id, lead_id, _, _ = _seed_case(
        postgres_engine,
        finding_lifecycle="closed",
    )

    with Session(postgres_engine, expire_on_commit=False) as session:
        lead = SqlAlchemyUserRepository(session).get(lead_id)
        assert lead is not None
        service = VerificationClosureService(
            SqlAlchemyVerificationClosureRepository(session),
            build_scenario_registry(),
        )
        with pytest.raises(ValueError, match="reason"):
            service.reopen_finding(
                lead,
                finding_id,
                reason="   ",
                occurred_at=NOW,
            )
        session.rollback()

    with Session(postgres_engine) as verification:
        assert verification.scalar(
            select(FindingRecord.lifecycle).where(FindingRecord.id == finding_id)
        ) == "closed"


def test_reopen_is_rejected_after_parent_case_commits_closed(
    postgres_engine: Engine,
) -> None:
    _, case_id, finding_id, lead_id, _, _ = _seed_case(
        postgres_engine,
        finding_lifecycle="closed",
    )

    with Session(postgres_engine, expire_on_commit=False) as session:
        lead = SqlAlchemyUserRepository(session).get(lead_id)
        assert lead is not None
        repository = SqlAlchemyVerificationClosureRepository(session)
        planning = _planning_service(session, repository)
        planning.transition_case(lead, case_id, "close", occurred_at=NOW)
        session.commit()

    with Session(postgres_engine, expire_on_commit=False) as session:
        lead = SqlAlchemyUserRepository(session).get(lead_id)
        assert lead is not None
        service = VerificationClosureService(
            SqlAlchemyVerificationClosureRepository(session),
            build_scenario_registry(),
        )
        with pytest.raises(ValueError, match="after ReviewCase closure"):
            service.reopen_finding(
                lead,
                finding_id,
                reason="Attempt reopen after closure",
                occurred_at=NOW,
            )
        session.rollback()

    with Session(postgres_engine) as verification:
        assert verification.scalar(
            select(FindingRecord.lifecycle).where(FindingRecord.id == finding_id)
        ) == "closed"
