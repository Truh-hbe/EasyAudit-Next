from typing import Protocol

from easyaudit_next.platform.domain.ids import OrganizationId
from easyaudit_next.review_core.domain.ids import FindingId, ReviewCaseId
from easyaudit_next.review_core.domain.models import Finding
from easyaudit_next.review_core.domain.repositories import RectificationRepository


class VerificationClosureRepository(RectificationRepository, Protocol):
    """Persistence capabilities used only by the M2.5 verification/closure slice."""

    def lock_finding_for_verification(
        self,
        organization_id: OrganizationId,
        finding_id: FindingId,
    ) -> Finding | None: ...

    def list_findings_for_closure(
        self,
        organization_id: OrganizationId,
        case_id: ReviewCaseId,
    ) -> tuple[Finding, ...]: ...
