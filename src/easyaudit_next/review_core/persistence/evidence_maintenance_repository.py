"""Read-only Evidence queries for the operator commands (orphan cleanup, integrity check).

Deliberately organization-agnostic: a bucket holds every organization's objects, so the question
"is this key referenced?" is global. Never used by request handling.
"""

from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.orm import Session

from easyaudit_next.platform.domain.ids import OrganizationId
from easyaudit_next.review_core.domain.ids import EvidenceId
from easyaudit_next.review_core.domain.models import Evidence
from easyaudit_next.review_core.persistence.models import EvidenceRecord
from easyaudit_next.review_core.persistence.rectification_repositories import (
    SqlAlchemyRectificationRepository,
)


class SqlAlchemyEvidenceMaintenanceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def referenced(self, storage_keys: Collection[str]) -> set[str]:
        if not storage_keys:
            return set()
        return set(
            self._session.scalars(
                select(EvidenceRecord.storage_key).where(
                    EvidenceRecord.storage_key.in_(list(storage_keys))
                )
            )
        )

    def page(
        self,
        organization_id: OrganizationId | None,
        after: EvidenceId | None,
        size: int,
    ) -> list[Evidence]:
        """Keyset pagination by id, so each batch is its own short read."""
        statement = select(EvidenceRecord).order_by(EvidenceRecord.id).limit(size)
        if organization_id is not None:
            statement = statement.where(EvidenceRecord.organization_id == organization_id)
        if after is not None:
            statement = statement.where(EvidenceRecord.id > after)
        return [
            SqlAlchemyRectificationRepository._evidence_to_domain(record)
            for record in self._session.scalars(statement)
        ]
