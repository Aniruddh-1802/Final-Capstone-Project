"""Scheduled-job logic shared by Airflow, the fallback scheduler and the command-line scripts.

Orchestrators (the DAGs, APScheduler) only CALL these functions or the scripts around them; none of the business logic
lives in a DAG file. Every function is safe to retry: loading is idempotent (file hash + key checks) and a report run
just writes new files.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import PipelineRun
from etl.incremental import find_new_files
from etl.pipeline import RunResult, process_files
from etl.reports import ReportResult, generate_report

log = logging.getLogger("etl.jobs")
DEFAULT_CHECK_REJECT_RATIO = 0.05  # warn operations earlier than the pipeline's hard stop (MAX_REJECT_RATIO, 0.20)
WEEKLY_REPORTS = ("readmission_summary", "admissions_trend")
REPORT_FORMATS = ("xlsx", "csv")


def max_run_id(engine: Engine) -> int:
    """Highest pipeline_runs.run_id (0 when there are no runs); a DAG run uses it as its 'before' marker."""
    with Session(engine) as session:
        return int(session.scalar(select(func.coalesce(func.max(PipelineRun.run_id), 0))) or 0)


def pending_files(engine: Engine, incoming_dir: str | Path | None = None) -> list[Path]:
    """CSV files in the incoming folder whose hash has no SUCCESS run, in name order."""
    settings = get_settings()
    folder = Path(incoming_dir) if incoming_dir else settings.resolve_path(settings.incoming_dir)
    with engine.connect() as conn:
        return find_new_files(folder, conn)


def scan_and_load(engine: Engine, triggered_by: str = "scan") -> list[RunResult]:
    """Process every new file (the same thing as ``python -m etl.pipeline --scan``)."""
    files = pending_files(engine)
    log.info("scan found %d new file(s): %s", len(files), [f.name for f in files])
    return process_files(files, triggered_by, engine=engine)


@dataclass
class CheckResult:
    """Outcome of checking the pipeline runs created after a marker."""

    ok: bool
    no_op: bool
    runs: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def check_runs(engine: Engine, after_run_id: int, max_reject_ratio: float = DEFAULT_CHECK_REJECT_RATIO) -> CheckResult:
    """Fail when a run after ``after_run_id`` is FAILED, still RUNNING, does not reconcile, or rejected too many rows.

    No runs at all means there was simply no new file: that is a successful no-op, not a failure.
    """
    with Session(engine) as session:
        rows = session.scalars(select(PipelineRun).where(PipelineRun.run_id > after_run_id).order_by(PipelineRun.run_id)).all()
        runs = [{"run_id": r.run_id, "file": r.source_file, "status": r.status, "read": r.rows_read, "loaded": r.rows_loaded,
                 "rejected": r.rows_rejected, "skipped": r.rows_skipped_existing, "error": r.error_message} for r in rows]
    if not runs:
        return CheckResult(ok=True, no_op=True)
    problems: list[str] = []
    for r in runs:
        ratio = (r["rejected"] / r["read"]) if r["read"] else 0.0
        r["reject_ratio"] = round(ratio, 6)
        if r["status"] == "FAILED":
            problems.append(f"run {r['run_id']} ({r['file']}) FAILED: {r['error']}")
        elif r["status"] == "RUNNING":
            problems.append(f"run {r['run_id']} ({r['file']}) is still RUNNING")
        elif r["status"] == "SUCCESS":
            if r["read"] != r["loaded"] + r["rejected"] + r["skipped"]:
                problems.append(f"run {r['run_id']} ({r['file']}) does not reconcile")
            if ratio > max_reject_ratio:
                problems.append(f"run {r['run_id']} ({r['file']}) rejected {ratio:.1%} of rows (limit {max_reject_ratio:.1%})")
    return CheckResult(ok=not problems, no_op=False, runs=runs, problems=problems)


def summary_lines(result: CheckResult) -> list[str]:
    """Human-readable lines for the DAG's record_summary task."""
    if result.no_op:
        return ["no new files: nothing to load (successful no-op)"]
    lines = [f"run {r['run_id']} {r['file']}: {r['status']} read={r['read']} loaded={r['loaded']} rejected={r['rejected']} "
             f"skipped_existing={r['skipped']} reject_ratio={r['reject_ratio']:.2%}" for r in result.runs]
    lines.append(f"total loaded={sum(r['loaded'] for r in result.runs)} rejected={sum(r['rejected'] for r in result.runs)}")
    return lines


def run_weekly_reports(engine: Engine, triggered_by: str = "airflow", save_dir: str | Path | None = None) -> list[ReportResult]:
    """readmission_summary and admissions_trend as XLSX and CSV into data/reports, one report_runs row each."""
    settings = get_settings()
    folder = Path(save_dir) if save_dir else settings.resolve_path(settings.reports_dir)
    results = [generate_report(engine, report, {}, fmt, triggered_by, save_dir=folder)
               for report in WEEKLY_REPORTS for fmt in REPORT_FORMATS]
    log.info("weekly reports written to %s: %s", folder, [r.filename for r in results])
    return results
