#!/bin/bash
# Start Airflow (standalone: api-server, scheduler, dag-processor, triggerer) inside WSL2 with this project's DAG folder.
#   wsl -d Ubuntu-Airflow -u root -- bash "/mnt/c/.../Aniruddh_Healthcare/scripts/airflow_standalone.sh"
# Airflow lives in its OWN virtualenv (/opt/airflow-venv), never in the project venv (its pinned packages would conflict with
# FastAPI and Pydantic). AIRFLOW_HOME is on the Linux filesystem because SQLite is unreliable on the Windows mount.
# The DAG tasks call the Windows project Python (venv/Scripts/python.exe) through WSL interop, so no project code runs
# inside the Airflow environment and the database stays reachable on the Windows 127.0.0.1.
set -eu
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/opt/airflow-venv/bin:$PATH"   # standalone starts its components by name (airflow scheduler, ...)
export AIRFLOW_HOME="${AIRFLOW_HOME:-/opt/airflow_home}"
export AIRFLOW__CORE__DAGS_FOLDER="$PROJECT/src/airflow/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES=False
export AIRFLOW__DAG_PROCESSOR__MIN_FILE_PROCESS_INTERVAL=10
export AIRFLOW__DAG_PROCESSOR__REFRESH_INTERVAL=10
export HC_PROJECT_ROOT="$PROJECT"
mkdir -p "$AIRFLOW_HOME"
echo "AIRFLOW_HOME=$AIRFLOW_HOME  DAGS=$AIRFLOW__CORE__DAGS_FOLDER"
exec /opt/airflow-venv/bin/airflow standalone
