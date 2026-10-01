from sqlalchemy import select

from easyaudit_next.platform.domain.ids import OrganizationId
from easyaudit_next.review_core.domain.ids import FindingId, ReviewCaseId
from easyaudit_next.review_core.domain.models import Finding, ReviewCase
from easyaudit_next.review_core.persistence.models import FindingRecord, ReviewCaseRecord
from easyaudit_next.review_core.persistence.rectification_repositories import (
    SqlAlchemyRectificationRepository,
)


class SqlAlchemyVerificationClosureRepository(SqlAlchemyRectificationRepository):
    """M2.5 persistence with Case-level verification/closure coordination."""

    def lock_case_for_closure(
        self,
        organization_id: OrganizationId,
        case_id: ReviewCaseId,
    ) -> ReviewCase | None:
        record = self._session.scalar(
            select(ReviewCaseRecord)
            .where(
                ReviewCaseRecord.organization_id == organization_id,
                ReviewCaseRecord.id == case_id,
            )
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        return self._case_to_domain(record) if record is not None else None

    def lock_finding_for_verification(
        self,
        organization_id: OrganizationId,
        finding_id: FindingId,
    ) -> Finding | None:
        record = self._session.scalar(
            select(FindingRecord)
            .where(
                FindingRecord.organization_id == organization_id,
                FindingRecord.id == finding_id,
            )
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        return self._finding_to_domain(record) if record is not None else None

    def list_findings_for_closure(
        self,
        organization_id: OrganizationId,
        case_id: ReviewCaseId,
    ) -> tuple[Finding, ...]:
        records = self._session.scalars(
            select(FindingRecord)
            .where(
                FindingRecord.organization_id == organization_id,
                FindingRecord.case_id == case_id,
            )
            .order_by(FindingRecord.raised_at.desc(), FindingRecord.id)
            .execution_options(populate_existing=True)
        )
        return tuple(self._finding_to_domain(record) for record in records)
