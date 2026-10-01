from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from easyaudit_next.infrastructure.database import Base


class SchedulerRunRecord(Base):
    """One execution attempt of an externally scheduled job.

    Operational record, not business truth: it never decides whether a run is skipped and never
    participates in deduplication (Notification's unique index does that). A row left in
    `running` means the process died before the final update.
    """

    __tablename__ = "scheduler_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')", name="ck_scheduler_runs_status"
        ),
        CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)", name="ck_scheduler_runs_finished"
        ),
        CheckConstraint(
            "scanned_count >= 0 AND created_count >= 0 AND deduped_count >= 0 "
            "AND failed_count >= 0",
            name="ck_scheduler_runs_counts",
        ),
        CheckConstraint(
            "job_key = btrim(job_key) AND job_key <> '' AND "
            "occurrence_key = btrim(occurrence_key) AND occurrence_key <> ''",
            name="ck_scheduler_runs_keys",
        ),
        Index("ix_scheduler_runs_job_started", "job_key", text("started_at DESC")),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    job_key: Mapped[str] = mapped_column(String(64))
    occurrence_key: Mapped[str] = mapped_column(String(200))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    scanned_count: Mapped[int] = mapped_column(Integer, server_default="0")
    created_count: Mapped[int] = mapped_column(Integer, server_default="0")
    deduped_count: Mapped[int] = mapped_column(Integer, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, server_default="0")
    error_summary: Mapped[str | None] = mapped_column(String(500))
