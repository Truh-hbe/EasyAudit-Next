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
from sqlalchemy.dialects.postgresql import JSONB
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


class ReviewPlanRecord(Base):
    __tablename__ = "review_plans"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_review_plans_id_organization"),
        ForeignKeyConstraint(
            ["created_by", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_review_plans_creator_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint("title = btrim(title) AND title <> ''", name="ck_review_plans_title"),
        CheckConstraint(
            "planned_end_at IS NULL OR planned_start_at IS NULL "
            "OR planned_end_at >= planned_start_at",
            name="ck_review_plans_dates",
        ),
        Index("ix_review_plans_organization", "organization_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", name="fk_review_plans_organization", ondelete="RESTRICT"),
    )
    title: Mapped[str] = mapped_column(String(300))
    planned_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReviewCaseRecord(Base):
    __tablename__ = "review_cases"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_review_cases_id_organization"),
        ForeignKeyConstraint(
            ["plan_id", "organization_id"],
            ["review_plans.id", "review_plans.organization_id"],
            name="fk_review_cases_plan_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["scenario_version_id", "organization_id"],
            ["scenario_versions.id", "scenario_versions.organization_id"],
            name="fk_review_cases_scenario_version_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_review_cases_creator_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint("title = btrim(title) AND title <> ''", name="ck_review_cases_title"),
        CheckConstraint(
            "lifecycle IN ('draft', 'scheduled', 'in_progress', "
            "'awaiting_closure', 'closed', 'cancelled')",
            name="ck_review_cases_lifecycle",
        ),
        Index("ix_review_cases_organization_lifecycle", "organization_id", "lifecycle"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("organizations.id", name="fk_review_cases_organization", ondelete="RESTRICT"),
    )
    plan_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    scenario_version_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(300))
    lifecycle: Mapped[str] = mapped_column(String(32))
    created_by: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CaseMemberRecord(Base):
    __tablename__ = "case_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["case_id", "organization_id"],
            ["review_cases.id", "review_cases.organization_id"],
            name="fk_case_members_case_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_case_members_user_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "role_key = btrim(role_key) AND role_key <> ''", name="ck_case_members_role"
        ),
        Index("ix_case_members_organization_user", "organization_id", "user_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    case_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    role_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FindingRecord(Base):
    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_findings_id_organization"),
        UniqueConstraint(
            "id", "case_id", "organization_id", name="uq_findings_id_case_organization"
        ),
        ForeignKeyConstraint(
            ["case_id", "organization_id"],
            ["review_cases.id", "review_cases.organization_id"],
            name="fk_findings_case_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["raised_by", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_findings_raiser_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint("title = btrim(title) AND title <> ''", name="ck_findings_title"),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_findings_severity",
        ),
        CheckConstraint(
            "lifecycle IN ('open', 'rectifying', 'verifying', 'closed', 'voided')",
            name="ck_findings_lifecycle",
        ),
        Index("ix_findings_organization_case", "organization_id", "case_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    case_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String(20))
    lifecycle: Mapped[str] = mapped_column(String(32))
    raised_by: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FindingParticipantRecord(Base):
    __tablename__ = "finding_participants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["finding_id", "organization_id"],
            ["findings.id", "findings.organization_id"],
            name="fk_finding_participants_finding_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_finding_participants_user_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["department_id", "organization_id"],
            ["departments.id", "departments.organization_id"],
            name="fk_finding_participants_department_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "num_nonnulls(user_id, department_id) = 1",
            name="ck_finding_participants_actor_xor",
        ),
        CheckConstraint(
            "role_key = btrim(role_key) AND role_key <> ''",
            name="ck_finding_participants_role",
        ),
        Index(
            "uq_finding_participants_user_role",
            "finding_id",
            "user_id",
            "role_key",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_finding_participants_department_role",
            "finding_id",
            "department_id",
            "role_key",
            unique=True,
            postgresql_where=text("department_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    finding_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    user_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    department_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    role_key: Mapped[str] = mapped_column(String(100))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ActionItemRecord(Base):
    __tablename__ = "action_items"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_action_items_id_organization"),
        ForeignKeyConstraint(
            ["finding_id", "organization_id"],
            ["findings.id", "findings.organization_id"],
            name="fk_action_items_finding_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint("title = btrim(title) AND title <> ''", name="ck_action_items_title"),
        CheckConstraint(
            "lifecycle IN ('todo', 'in_progress', 'done', 'cancelled')",
            name="ck_action_items_lifecycle",
        ),
        Index("ix_action_items_organization_finding", "organization_id", "finding_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    finding_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(300))
    lifecycle: Mapped[str] = mapped_column(String(32))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActionAssigneeRecord(Base):
    __tablename__ = "action_assignees"
    __table_args__ = (
        ForeignKeyConstraint(
            ["action_item_id", "organization_id"],
            ["action_items.id", "action_items.organization_id"],
            name="fk_action_assignees_action_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_action_assignees_user_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["department_id", "organization_id"],
            ["departments.id", "departments.organization_id"],
            name="fk_action_assignees_department_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "num_nonnulls(user_id, department_id) = 1",
            name="ck_action_assignees_actor_xor",
        ),
        CheckConstraint(
            "role IN ('primary', 'collaborator')",
            name="ck_action_assignees_role",
        ),
        Index(
            "uq_action_assignees_user_role",
            "action_item_id",
            "user_id",
            "role",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_action_assignees_department_role",
            "action_item_id",
            "department_id",
            "role",
            unique=True,
            postgresql_where=text("department_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    action_item_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    user_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    department_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    role: Mapped[str] = mapped_column(String(32))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SubmissionRecord(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_submissions_id_organization"),
        ForeignKeyConstraint(
            ["case_id", "organization_id"],
            ["review_cases.id", "review_cases.organization_id"],
            name="fk_submissions_case_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["finding_id", "case_id", "organization_id"],
            ["findings.id", "findings.case_id", "findings.organization_id"],
            name="fk_submissions_finding_case_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["submitted_by", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_submissions_submitter_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "purpose IN ('finding_report', 'rectification', 'verification', 'closure')",
            name="ck_submissions_purpose",
        ),
        Index("ix_submissions_organization_case", "organization_id", "case_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    case_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    finding_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    purpose: Mapped[str] = mapped_column(String(32))
    submitted_by: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_json: Mapped[dict[str, object]] = mapped_column("payload", JSONB, default=dict)


class ActivityRecord(Base):
    __tablename__ = "activities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["actor_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_activities_actor_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["review_case_id", "organization_id"],
            ["review_cases.id", "review_cases.organization_id"],
            name="fk_activities_case_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["finding_id", "organization_id"],
            ["findings.id", "findings.organization_id"],
            name="fk_activities_finding_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["action_item_id", "organization_id"],
            ["action_items.id", "action_items.organization_id"],
            name="fk_activities_action_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["submission_id", "organization_id"],
            ["submissions.id", "submissions.organization_id"],
            name="fk_activities_submission_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "num_nonnulls(review_case_id, finding_id, action_item_id, submission_id) = 1",
            name="ck_activities_exactly_one_target",
        ),
        CheckConstraint(
            "event_type = btrim(event_type) AND event_type <> ''", name="ck_activities_event_type"
        ),
        Index("ix_activities_organization_occurred", "organization_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    actor_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(100))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    review_case_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    finding_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    action_item_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    submission_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    metadata_json: Mapped[dict[str, object]] = mapped_column("metadata", JSONB, default=dict)
