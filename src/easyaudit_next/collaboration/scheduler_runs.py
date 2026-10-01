from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, select, text, update
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

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


JOB_AUTOMATIC_REMINDER_SWEEP = "automatic_reminder_sweep"


def start_run(
    session: Session,
    *,
    job_key: str,
    occurrence_key: str,
    as_of: datetime,
    started_at: datetime,
) -> UUID:
    run_id = uuid4()
    session.add(
        SchedulerRunRecord(
            id=run_id,
            job_key=job_key,
            occurrence_key=occurrence_key,
            as_of=as_of,
            started_at=started_at,
            status="running",
        )
    )
    session.flush()
    return run_id


def finish_run(
    session: Session,
    run_id: UUID,
    *,
    status: str,
    finished_at: datetime,
    scanned_count: int,
    created_count: int,
    deduped_count: int,
    failed_count: int,
    error_summary: str | None,
) -> None:
    if status not in ("succeeded", "failed"):
        raise ValueError("A finished run is either succeeded or failed")
    session.execute(
        update(SchedulerRunRecord)
        .where(SchedulerRunRecord.id == run_id)
        .values(
            status=status,
            finished_at=finished_at,
            scanned_count=scanned_count,
            created_count=created_count,
            deduped_count=deduped_count,
            failed_count=failed_count,
            error_summary=error_summary,
        )
    )


def latest_run(
    session: Session, job_key: str, *, status: str | None = None
) -> SchedulerRunRecord | None:
    statement = select(SchedulerRunRecord).where(SchedulerRunRecord.job_key == job_key)
    if status is not None:
        statement = statement.where(SchedulerRunRecord.status == status)
    return session.scalar(statement.order_by(SchedulerRunRecord.started_at.desc()).limit(1))
