"""FALLBACK scheduler (APScheduler). The Airflow DAGs in src/airflow/dags are the intended design; this runs the SAME two jobs
(same functions, same schedules) in one plain Python process for machines where Airflow cannot be installed.

    python scripts/scheduler.py                 # blocks; Ctrl+C to stop
    python scripts/scheduler.py --once etl      # run the ETL job now and exit (also: --once reports)

Trade-offs versus Airflow (honest): no web UI, no task graph, no per-task retry history; retries here are a simple loop;
runs are lost if this process is not running (no catch-up, which matches catchup=False). Idempotent loading makes a
double run harmless.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: E402
from apscheduler.triggers.cron import CronTrigger  # noqa: E402

from app.database import get_engine  # noqa: E402
from etl import jobs  # noqa: E402
from etl.pipeline import configure_logging  # noqa: E402

log = logging.getLogger("etl.scheduler")
RETRIES, RETRY_DELAY_SECONDS = 2, 120  # same policy as the DAGs: retries=2, 2 minutes apart


def with_retries(name: str, func, retries: int = RETRIES, delay: float = RETRY_DELAY_SECONDS) -> bool:
    """Run ``func`` up to ``retries + 1`` times; log a clear failure line and return False if every attempt fails."""
    for attempt in range(1, retries + 2):
        try:
            func()
            return True
        except Exception:  # noqa: BLE001 - any failure of a job must be retried and logged, never crash the scheduler
            log.exception("job %s attempt %d/%d failed", name, attempt, retries + 1)
            if attempt <= retries:
                time.sleep(delay)
    log.error("JOB FAILURE job=%s after %d attempts -- see logs/etl.log and the Pipeline Runs page", name, retries + 1)
    return False


def etl_job() -> None:
    """scan -> load -> check -> summary, raising on a quality problem so the retry policy applies."""
    engine = get_engine()
    marker = jobs.max_run_id(engine)
    jobs.scan_and_load(engine, triggered_by="scheduler")
    result = jobs.check_runs(engine, marker)
    for line in jobs.summary_lines(result):
        log.info(line)
    if not result.ok:
        raise RuntimeError("; ".join(result.problems))


def reports_job() -> None:
    jobs.run_weekly_reports(get_engine(), triggered_by="scheduler")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fallback scheduler for the ETL and the weekly reports")
    parser.add_argument("--once", choices=["etl", "reports"], help="run one job now, then exit")
    args = parser.parse_args(argv)
    configure_logging()
    if args.once:
        return 0 if with_retries(args.once, etl_job if args.once == "etl" else reports_job) else 1
    scheduler = BlockingScheduler()
    scheduler.add_job(lambda: with_retries("etl", etl_job), CronTrigger(minute=0), id="healthcare_incremental_etl", max_instances=1,
                      coalesce=True, misfire_grace_time=600)            # hourly, like @hourly
    scheduler.add_job(lambda: with_retries("reports", reports_job), CronTrigger(day_of_week="mon", hour=6, minute=0),
                      id="healthcare_weekly_report", max_instances=1, coalesce=True, misfire_grace_time=3600)  # Mondays 06:00
    log.info("fallback scheduler started: ETL hourly, reports Mondays 06:00 (Ctrl+C to stop)")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("scheduler stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
