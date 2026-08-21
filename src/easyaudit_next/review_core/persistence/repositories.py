from sqlalchemy import select
from sqlalchemy.orm import Session

from easyaudit_next.platform.domain.ids import OrganizationId
from easyaudit_next.review_core.domain.ids import ScenarioDefinitionId, ScenarioVersionId
from easyaudit_next.review_core.domain.models import (
    ScenarioDefinition,
    ScenarioKey,
    ScenarioVersion,
    ScenarioVersionPublication,
)
from easyaudit_next.review_core.persistence.models import ScenarioRecord, ScenarioVersionRecord


class SqlAlchemyScenarioCatalogRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_scenario(self, scenario: ScenarioDefinition) -> None:
        self._session.add(
            ScenarioRecord(
                id=scenario.id,
                organization_id=scenario.organization_id,
                key=scenario.key,
                name=scenario.name,
                is_active=scenario.is_active,
            )
        )
        self._session.flush()

    def add_version(self, publication: ScenarioVersionPublication) -> None:
        self._session.add(
            ScenarioVersionRecord(
                id=publication.id,
                scenario_id=publication.scenario_id,
                organization_id=publication.organization_id,
                version=publication.version,
                published_at=publication.published_at,
            )
        )
        self._session.flush()

    def get_by_key(
        self,
        organization_id: OrganizationId,
        key: ScenarioKey,
    ) -> ScenarioDefinition | None:
        record = self._session.scalar(
            select(ScenarioRecord).where(
                ScenarioRecord.organization_id == organization_id,
                ScenarioRecord.key == key,
            )
        )
        if record is None:
            return None
        return ScenarioDefinition(
            id=ScenarioDefinitionId(record.id),
            organization_id=OrganizationId(record.organization_id),
            key=ScenarioKey(record.key),
            name=record.name,
            is_active=record.is_active,
        )

    def get_version(
        self,
        scenario_id: ScenarioDefinitionId,
        version: ScenarioVersion,
    ) -> ScenarioVersionPublication | None:
        record = self._session.scalar(
            select(ScenarioVersionRecord).where(
                ScenarioVersionRecord.scenario_id == scenario_id,
                ScenarioVersionRecord.version == version,
            )
        )
        if record is None:
            return None
        return ScenarioVersionPublication(
            id=ScenarioVersionId(record.id),
            scenario_id=ScenarioDefinitionId(record.scenario_id),
            organization_id=OrganizationId(record.organization_id),
            version=ScenarioVersion(record.version),
            published_at=record.published_at,
        )
