"""Operational tables: audit logs, pipeline runs, data-quality issues, report runs."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, CHAR, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MYSQL_TABLE_ARGS, Base
from app.models.users import ROLES

AUDIT_ACTIONS = ("CREATE", "UPDATE", "DELETE", "EXPORT")
RUN_STATUSES = ("RUNNING", "SUCCESS", "FAILED", "SKIPPED_DUPLICATE_FILE")
DQ_SEVERITIES = ("error", "warning", "info")
DQ_ACTIONS = ("rejected", "corrected", "flagged", "metric")


class AuditLog(Base):
    """Who changed what, with before and after values."""

    __tablename__ = "audit_logs"
    # Audit lists are newest first with a date window; the trail of one record is looked up by entity
    # (see docs/performance_notes.md; an extra (username, created_at) index was measured and rejected).
    __table_args__ = (Index("ix_audit_logs_created_at", "created_at"),
                      Index("ix_audit_logs_entity", "entity_type", "entity_id"), MYSQL_TABLE_ARGS)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("app_users.user_id", ondelete="SET NULL"), nullable=True
    )
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    role: Mapped[str] = mapped_column(Enum(*ROLES, name="audit_role"), nullable=False)
    action: Mapped[str] = mapped_column(Enum(*AUDIT_ACTIONS, name="audit_action"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(40), nullable=False)
    before_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)


class PipelineRun(Base):
    """Run history and the ETL monitor."""

    __tablename__ = "pipeline_runs"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_file: Mapped[str] = mapped_column(String(255), nullable=False)
    file_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    status: Mapped[str] = mapped_column(Enum(*RUN_STATUSES, name="run_status"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rows_read: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    rows_loaded: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    rows_skipped_existing: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    dq_summary_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(50), nullable=False)


class DqIssue(Base):
    """Row-level data-quality finding. encounter_id has no FK: rejected rows never reach encounters."""

    __tablename__ = "dq_issues"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    issue_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pipeline_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    encounter_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rule_name: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(Enum(*DQ_SEVERITIES, name="dq_severity"), nullable=False)
    column_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bad_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(Enum(*DQ_ACTIONS, name="dq_action"), nullable=False)


class ReportRun(Base):
    """History of generated reports (manual or scheduled)."""

    __tablename__ = "report_runs"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    report_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    filters_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(50), nullable=False)
