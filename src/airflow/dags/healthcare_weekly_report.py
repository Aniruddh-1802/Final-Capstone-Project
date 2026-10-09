"""DAG: weekly report. One task that calls the project's report generator (the same code the API uses).

    generate_weekly_reports   scripts/run_weekly_reports.py

Writes readmission_summary and admissions_trend as XLSX and CSV into data/reports/ and one report_runs row per file
(triggered_by="airflow"). Orchestration only; see healthcare_incremental_etl.py for the conventions used here.
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
RUN = f'cd "{PROJECT_ROOT}" && "{PROJECT_PYTHON}"'  # the script adds src/ to its own path


def log_failure(context: dict) -> None:
    ti = context.get("task_instance")
    log.error("REPORT FAILURE dag=%s task=%s run_id=%s try=%s", context.get("dag").dag_id if context.get("dag") else "?",
              getattr(ti, "task_id", "?"), context.get("run_id"), getattr(ti, "try_number", "?"))


with DAG(
    dag_id="healthcare_weekly_report",
    description="Weekly readmission summary and admissions trend (XLSX and CSV)",
    start_date=datetime(2026, 10, 1),
    schedule="0 6 * * 1",   # Mondays 06:00
    catchup=False,
    max_active_runs=1,
    default_args={"owner": "healthcare", "retries": 2, "retry_delay": timedelta(minutes=5), "on_failure_callback": log_failure},
    tags=["healthcare", "reports"],
) as dag:
    BashOperator(task_id="generate_weekly_reports", bash_command=f"{RUN} scripts/run_weekly_reports.py --triggered-by airflow")
