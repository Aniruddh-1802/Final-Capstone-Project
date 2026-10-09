"""Pipeline orchestration: extract -> transform -> validate -> load, with one run record per file.

All writes of a file's data happen in ONE transaction, together with the reconciliation check, so a failure leaves
none of that file's rows behind. The ``pipeline_runs`` row is written in its own transactions (before and after)
so a failed run is still recorded.

CLI (run from ``src/`` or with PYTHONPATH=src):
    python -m etl.pipeline --file PATH
    python -m etl.pipeline --scan
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, insert, select, update

from app.config import get_settings
from app.database import get_engine
from app.models import (
    DqIssue, PipelineRun, RefAdmissionSource, RefAdmissionType, RefDischargeDisposition,
)
from etl.extract import read_batch
from etl.incremental import find_new_files, loaded_hashes, sha256_file
from etl.load import load_tables
from etl.quality import BatchRejectedError, validate, write_rejected
from etl.transform import build_tables, standardise_columns
from utils.logging_config import setup_logging

log = logging.getLogger("etl.pipeline")  # explicit: __name__ is "__main__" under python -m etl.pipeline


class ReconciliationError(RuntimeError):
    """rows_read != rows_loaded + rows_rejected + rows_skipped_existing."""


class ReferenceDataError(RuntimeError):
    """Reference lookup tables are empty (run db/seed_reference.py first)."""


@dataclass
class RunResult:
    """Outcome of one pipeline run (mirrors the pipeline_runs row)."""

    run_id: int
    status: str
    source_file: str
    rows_read: int = 0
    rows_loaded: int = 0
    rows_rejected: int = 0
    rows_skipped_existing: int = 0
    error_message: str | None = None


@contextmanager
def _stage(name: str) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        log.info("stage=%s duration=%.2fs", name, time.perf_counter() - start)


def _reference_ids(engine: Engine) -> dict[str, set[int]]:
    models = {"admission_type": RefAdmissionType, "admission_source": RefAdmissionSource,
              "discharge_disposition": RefDischargeDisposition}
    with engine.connect() as conn:
        ids = {name: set(conn.execute(select(m.id)).scalars()) for name, m in models.items()}
    if not all(ids.values()):
        raise ReferenceDataError("Reference tables are empty; run db/seed_reference.py first")
    return ids


def _close_run(engine: Engine, result: RunResult, summary: dict[str, Any] | None, issues: list[dict[str, Any]],
               chunk_size: int) -> None:
    """Write the final counts, summary and dq_issues of a run."""
    with engine.begin() as conn:
        conn.execute(update(PipelineRun).where(PipelineRun.run_id == result.run_id).values(
            status=result.status, finished_at=datetime.now(), rows_read=result.rows_read,
            rows_loaded=result.rows_loaded, rows_rejected=result.rows_rejected,
            rows_skipped_existing=result.rows_skipped_existing, dq_summary_json=summary,
            error_message=result.error_message))
        rows = [{**i, "run_id": result.run_id} for i in issues]
        for start in range(0, len(rows), chunk_size):
            conn.execute(insert(DqIssue), rows[start:start + chunk_size])
    log.info("run %d closed: status=%s read=%d loaded=%d rejected=%d skipped_existing=%d", result.run_id,
             result.status, result.rows_read, result.rows_loaded, result.rows_rejected, result.rows_skipped_existing)


def _empty_tables() -> dict[str, Any]:
    return {}


def run_pipeline(path: str | Path, triggered_by: str = "cli", engine: Engine | None = None,
                 rejected_dir: str | Path | None = None, max_reject_ratio: float | None = None,
                 chunk_size: int | None = None) -> RunResult:
    """Process one batch file and return its run record. Never raises for data problems: they set status FAILED."""
    settings = get_settings()
    engine = engine or get_engine()
    path = Path(path)
    rejected_dir = Path(rejected_dir) if rejected_dir else settings.resolve_path(settings.rejected_dir)
    ratio = settings.max_reject_ratio if max_reject_ratio is None else max_reject_ratio
    chunk = chunk_size or settings.chunk_size

    file_hash = sha256_file(path)
    with engine.begin() as conn:
        stale = conn.execute(update(PipelineRun).where(
            PipelineRun.file_hash == file_hash, PipelineRun.status == "RUNNING").values(
            status="FAILED", finished_at=datetime.now(),
            error_message="Interrupted: the process ended before this run was closed"))
        if stale.rowcount:
            log.warning("marked %d interrupted run(s) of %s as FAILED", stale.rowcount, path.name)
        run_id = conn.execute(insert(PipelineRun).values(
            source_file=path.name, file_hash=file_hash, status="RUNNING", started_at=datetime.now(),
            triggered_by=triggered_by)).inserted_primary_key[0]
        already_loaded = file_hash in loaded_hashes(conn)
    result = RunResult(run_id=run_id, status="RUNNING", source_file=path.name)
    log.info("run %d started for %s (sha256 %s...)", run_id, path.name, file_hash[:12])
    if already_loaded:
        result.status = "SKIPPED_DUPLICATE_FILE"
        _close_run(engine, result, None, [], chunk)
        return result

    summary: dict[str, Any] | None = None
    issues: list[dict[str, Any]] = []
    try:
        with _stage("extract"):
            df = standardise_columns(read_batch(path))
            result.rows_read = len(df)
        with _stage("validate"):
            clean, rejected, summary = validate(df, _reference_ids(engine), max_reject_ratio=ratio)
            issues = summary.pop("issues")
            write_rejected(rejected, path.name, rejected_dir)
            result.rows_rejected = summary["rows_rejected"]
        with _stage("transform"):
            tables = build_tables(clean) if len(clean) else _empty_tables()
        with _stage("load"), engine.begin() as conn:
            counts = load_tables(conn, tables, path.stem, chunk) if tables else {"loaded": 0, "skipped_existing": 0}
            result.rows_loaded, result.rows_skipped_existing = counts["loaded"], counts["skipped_existing"]
            if result.rows_read != result.rows_loaded + result.rows_rejected + result.rows_skipped_existing:
                raise ReconciliationError(
                    f"rows_read={result.rows_read} != loaded={result.rows_loaded} + rejected={result.rows_rejected} "
                    f"+ skipped_existing={result.rows_skipped_existing}")
            summary["load"] = counts
        result.status = "SUCCESS"
    except BatchRejectedError as exc:
        # The whole file is refused: nothing loads, so every row counts as rejected and the run still reconciles.
        summary, issues = {**exc.summary}, exc.issues
        summary.pop("issues", None)
        summary["rows_failing_rules"] = exc.summary["rows_rejected"]
        write_rejected(exc.rejected, path.name, rejected_dir)
        result.status, result.error_message = "FAILED", str(exc)
        result.rows_rejected, result.rows_loaded, result.rows_skipped_existing = result.rows_read, 0, 0
        log.error("run %d failed: %s", run_id, exc)
    except Exception as exc:  # noqa: BLE001 - any failure must close the run record as FAILED
        result.status, result.error_message = "FAILED", f"{type(exc).__name__}: {str(exc)[:500]}"
        result.rows_loaded, result.rows_skipped_existing = 0, 0
        log.exception("run %d failed", run_id)
    _close_run(engine, result, summary, issues, chunk)
    return result


def process_files(paths: list[Path], triggered_by: str, engine: Engine | None = None) -> list[RunResult]:
    """Run the pipeline for each path in order."""
    return [run_pipeline(p, triggered_by=triggered_by, engine=engine) for p in paths]


def configure_logging(log_dir: str | Path | None = None) -> logging.Logger:
    """Attach console + rotating-file handlers to the ``etl`` logger (all ``etl.*`` modules inherit them).

    The file is ``<log_dir>/etl.log``. The logger name must be ``etl`` (not ``pipeline``): module loggers are
    named ``etl.pipeline``, ``etl.load`` ... so only a logger called ``etl`` receives their records.
    """
    settings = get_settings()
    return setup_logging("etl", log_dir=log_dir or settings.resolve_path(settings.log_dir))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; exit code 1 if any run FAILED."""
    parser = argparse.ArgumentParser(prog="etl.pipeline", description="Load healthcare encounter batch files")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", type=Path, help="process one CSV file")
    group.add_argument("--scan", action="store_true", help="process every new file in INCOMING_DIR, in name order")
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging()
    if args.file:
        results = process_files([args.file], "cli")
    else:
        with get_engine().connect() as conn:
            files = find_new_files(settings.resolve_path(settings.incoming_dir), conn)
        log.info("scan found %d new file(s): %s", len(files), [f.name for f in files])
        results = process_files(files, "scan")
    return 1 if any(r.status == "FAILED" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())

