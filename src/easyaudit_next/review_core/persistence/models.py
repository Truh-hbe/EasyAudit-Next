from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from easyaudit_next.infrastructure.database import Base


class ScenarioRecord(Base):
    __tablename__ = "scenarios"
    __table_args__ = (
        UniqueConstraint("organization_id", "key", name="uq_scenarios_organization_key"),
        UniqueConstraint("id", "organization_id", name="uq_scenarios_id_organization"),
        CheckConstraint("key = btrim(key) AND key <> ''", name="ck_scenarios_key"),
        CheckConstraint("name = btrim(name) AND name <> ''", name="ck_scenarios_name"),
        Index("ix_scenarios_organization_active", "organization_id", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", name="fk_scenarios_organization", ondelete="RESTRICT"),
    )
    key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ScenarioVersionRecord(Base):
    __tablename__ = "scenario_versions"
    __table_args__ = (
        UniqueConstraint("scenario_id", "version", name="uq_scenario_versions_version"),
        UniqueConstraint("id", "organization_id", name="uq_scenario_versions_id_organization"),
        ForeignKeyConstraint(
            ["scenario_id", "organization_id"],
            ["scenarios.id", "scenarios.organization_id"],
            name="fk_scenario_versions_scenario_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint("version > 0", name="ck_scenario_versions_positive"),
        Index("ix_scenario_versions_organization", "organization_id", "scenario_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    scenario_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    organization_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
