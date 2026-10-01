"""Read-only Evidence queries for the operator commands (orphan cleanup, integrity check).

Deliberately organization-agnostic: a bucket holds every organization's objects, so the question
"is this key referenced?" is global. Never used by request handling.
"""

from collections.abc import Collection

from sqlalchemy import func, select, text
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

    def evidence_id_for_key(self, storage_key: str) -> str | None:
        found = self._session.scalar(
            select(EvidenceRecord.id).where(EvidenceRecord.storage_key == storage_key).limit(1)
        )
        return None if found is None else str(found)

    def count(self) -> int:
        return int(self._session.scalar(select(func.count()).select_from(EvidenceRecord)) or 0)

    def alembic_revisions(self) -> set[str]:
        """Every row, not one of them: more than one revision is itself a wrong database."""
        rows = self._session.scalars(text("SELECT version_num FROM alembic_version"))
        return {str(row) for row in rows}

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
