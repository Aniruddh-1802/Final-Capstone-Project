"""DAG: incremental ETL. Orchestration only: every task CALLS existing project code through the project's own Python.

    scan_for_new_files >> run_etl >> check_quality >> record_summary

* scan_for_new_files  scripts/scan_incoming.py     counts new files, remembers the current max pipeline run id (XCom)
* run_etl             python -m etl.pipeline --scan  loads every new file; exit 1 if any run FAILED
* check_quality       scripts/check_latest_run.py   fails on a FAILED run, a non-reconciling run or too many rejects;
                                                    no new file = a successful no-op
* record_summary      scripts/check_latest_run.py --summary   logs the counts

Idempotent tasks make retries safe: a file is loaded only if its hash has no SUCCESS run and its encounter ids are new.
Airflow runs in its own environment (see docs/runbook.md); this file imports nothing from the project and makes no
database call at import time, so it parses instantly. Verified against Apache Airflow 3.x (airflow.sdk, standard provider)
with a fallback import for 2.x.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

try:  # Airflow 3.x
    from airflow.providers.standard.operators.bash import BashOperator
    from airflow.sdk import DAG
except ImportError:  # Airflow 2.x
    from airflow import DAG
    from airflow.operators.bash import BashOperator

log = logging.getLogger(__name__)
PROJECT_ROOT = os.environ.get("HC_PROJECT_ROOT", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
PROJECT_PYTHON = os.environ.get("HC_PYTHON", os.path.join(PROJECT_ROOT, "venv", "Scripts", "python.exe"))
# Scripts add src/ to their own path. Modules run from src/ because `python -m` puts the current directory on sys.path
# (an inline PYTHONPATH is not forwarded from WSL to a Windows python.exe, which was found by running it).
RUN = f'cd "{PROJECT_ROOT}" && "{PROJECT_PYTHON}"'
RUN_MODULE = f'cd "{PROJECT_ROOT}/src" && "{PROJECT_PYTHON}"'
MAX_REJECT = os.environ.get("HC_CHECK_MAX_REJECT_RATIO", "0.05")
# Two minutes between retries; HC_RETRY_DELAY_SECONDS shortens it for demos and tests.
RETRY_DELAY = timedelta(seconds=int(os.environ.get("HC_RETRY_DELAY_SECONDS", "120")))


def log_failure(context: dict) -> None:
    """on_failure_callback: one clear line with the DAG, task and run ids (also visible in the scheduler log)."""
    ti = context.get("task_instance")
    log.error("PIPELINE FAILURE dag=%s task=%s run_id=%s try=%s -- see the task log and the Pipeline Runs page",
              context.get("dag").dag_id if context.get("dag") else "?", getattr(ti, "task_id", "?"),
              context.get("run_id"), getattr(ti, "try_number", "?"))


default_args = {"owner": "healthcare", "retries": 2, "retry_delay": RETRY_DELAY, "on_failure_callback": log_failure}

with DAG(
    dag_id="healthcare_incremental_etl",
    description="Load new encounter files, then check run quality",
    start_date=datetime(2026, 10, 1),
    schedule="@hourly",
    catchup=False,          # never queue missed hourly runs
    max_active_runs=1,      # two loads must never overlap
    default_args=default_args,
    tags=["healthcare", "etl"],
) as dag:
    scan_for_new_files = BashOperator(task_id="scan_for_new_files", bash_command=f"{RUN} scripts/scan_incoming.py")
    run_etl = BashOperator(task_id="run_etl", bash_command=f"{RUN_MODULE} -m etl.pipeline --scan")
    check_quality = BashOperator(
        task_id="check_quality",
        bash_command=(f"{RUN} scripts/check_latest_run.py --after-run-id "
                      "'{{ ti.xcom_pull(task_ids=\"scan_for_new_files\") }}' " + f"--max-reject-ratio {MAX_REJECT}"),
    )
    record_summary = BashOperator(
        task_id="record_summary",
        bash_command=(f"{RUN} scripts/check_latest_run.py --summary --after-run-id "
                      "'{{ ti.xcom_pull(task_ids=\"scan_for_new_files\") }}'"),
    )
    scan_for_new_files >> run_etl >> check_quality >> record_summary
