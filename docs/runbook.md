# Runbook

## Start everything (Windows, local)
1. Start MySQL (portable install): `C:\Users\reach\mysql\mysql-8.4.9-winx64\bin\mysqld.exe --defaults-file=C:\Users\reach\mysql\my.ini`
2. `venv\Scripts\activate`; `python scripts/smoke_test.py` must print PASS for every check.
3. API (from `src/`): `uvicorn app.main:app --reload` -> Swagger at http://127.0.0.1:8000/docs, health at `/health`.

## Load data
```
python scripts/prepare_batches.py                      # once; deterministic (seed 42)
python db/seed_reference.py && python db/seed_users.py
python scripts/apply_views.py                          # v_active_encounters, v_readmission_base
cd src
python -m etl.pipeline --file ..\data\incoming\encounters_batch_000_initial.csv
python -m etl.pipeline --scan                          # every new CSV in INCOMING_DIR, in name order
```
Exit code is 1 if any run FAILED. `data/incoming/faulty_batch.csv` is a deliberately bad test file: `--scan` would load its clean rows (see below); keep it out of the folder for a clean feed.

## Idempotency and failure policy
* **File level:** SHA-256 of the file; a hash with a SUCCESS run is skipped (`SKIPPED_DUPLICATE_FILE`).
* **Row level:** `encounter_id`s already in `encounters` (soft-deleted included) are pre-selected and skipped. A renamed or reordered copy therefore loads nothing.
* **One transaction per file:** all data writes and the reconciliation check commit together or not at all. Chunking (`CHUNK_SIZE`, default 5000) only controls statement size, never commit boundaries.
* **Reconciliation:** `rows_read = rows_loaded + rows_rejected + rows_skipped_existing` is checked inside the load transaction; a mismatch rolls the load back and fails the run.
* **File-level rejection** (rejected share above `MAX_REJECT_RATIO`, default 0.20): status FAILED, nothing loads, every row counts as rejected (`rows_rejected = rows_read`) so the run still reconciles; `dq_summary_json.rows_failing_rules` keeps the true number of rule failures.
* Any other exception: status FAILED, `error_message` set, none of the file's rows present; the same file can be retried (only SUCCESS blocks a hash).

## Demo sequence on the real data (run 2026-10-08)
| Run | File | Status | Read | Loaded | Rejected | Skipped existing | Note |
|---|---|---|---|---|---|---|---|
| 1 | `encounters_batch_000_initial.csv` | SUCCESS | 81,412 | 81,412 | 0 | 0 | initial load, about 12 s |
| 2 | `encounters_batch_001.csv` | SUCCESS | 5,089 | 5,089 | 0 | 0 | incremental batch |
| 3 | `encounters_batch_001.csv` (again) | SKIPPED_DUPLICATE_FILE | 0 | 0 | 0 | 0 | same hash, no work done |
| 4 | reordered copy of batch 001, new file name | SUCCESS | 5,089 | 0 | 0 | 5,089 | different hash, all rows already present |
| 5 | `faulty_batch.csv` (from held-back batch 003) | SUCCESS | 5,088 | 5,065 | 23 | 0 | 23 rows quarantined in `data/rejected/faulty_batch_rejected.csv`; 5 malformed ICD codes set to NULL |

After the sequence: 91,566 encounters (= 81,412 + 5,089 + 5,065), 91,566 distinct encounter_ids, 91,566 outcomes, 65,472 patients, 272,970 diagnosis rows, 107,801 encounter-medication rows, 20 drugs, 72 specialties, 16 payers, no encounters without an outcome, no orphan patients.
`dq_issues` for these runs: DQ01 x3, DQ02 x5, DQ03 x5, DQ05 x5, DQ09 x5 rejected; DQ06 x5 corrected; DQ12 x4 and DQ13 x283 flagged; DQ11 metrics.

Note: because the faulty file came from held-back batch 003, a later clean load of the genuine `encounters_batch_003.csv` will skip the 5,065 rows already loaded and add only the 23 that were rejected, a realistic "corrected resend". The five encounters whose ICD code was nulled by the faulty run keep that NULL.

## KPI verification
`python scripts/verify_kpis.py` recomputes the headline numbers and the by-age-group rates in pandas from the raw CSV (restricted to the loaded encounter ids) and prints PASS or FAIL per metric: 59 of 59 passed.

## Scheduling with Airflow (L17)
Two DAGs in `src/airflow/dags/` run the same project code as the command line; they contain no business logic.

| DAG | Schedule | Tasks |
|---|---|---|
| `healthcare_incremental_etl` | `@hourly`, `catchup=False`, `max_active_runs=1`, retries 2 (2 minutes apart), failure callback | `scan_for_new_files` >> `run_etl` >> `check_quality` >> `record_summary` |
| `healthcare_weekly_report` | Mondays 06:00 (`0 6 * * 1`), `catchup=False`, retries 2 | `generate_weekly_reports` |

* `scan_for_new_files` (`scripts/scan_incoming.py`) counts new files and prints a JSON line with the current maximum pipeline run id; Airflow stores it as the task's XCom.
* `run_etl` is `python -m etl.pipeline --scan` (exit 1 if any run FAILED, so a bad file turns the task red and triggers the retries).
* `check_quality` (`scripts/check_latest_run.py --after-run-id <marker>`) looks only at the runs created since the scan. It fails on a FAILED run, a run that does not reconcile, a run still RUNNING, or a reject ratio above `HC_CHECK_MAX_REJECT_RATIO` (default 5%, deliberately tighter than the pipeline's own 20% hard stop so operations hear about a dirty file that still loaded). **No new file is a successful no-op.**
* `record_summary` logs the counts. The weekly DAG writes `readmission_summary` and `admissions_trend` as XLSX and CSV into `data/reports/` and one `report_runs` row each with `triggered_by = airflow` (same generator as the API).

### Install (Windows: Airflow needs Linux, so WSL2)
Airflow runs in its own virtualenv inside a WSL2 Ubuntu; never install it in the project venv (its pinned packages conflict with FastAPI and Pydantic).
```
# once, in PowerShell: a user-level Ubuntu 22.04 (no admin rights needed)
curl.exe -L -o ubuntu-jammy.rootfs.tar.gz https://cloud-images.ubuntu.com/wsl/jammy/current/ubuntu-jammy-wsl-amd64-ubuntu22.04lts.rootfs.tar.gz
wsl --import Ubuntu-Airflow C:\Users\<you>\wsl\Ubuntu-Airflow ubuntu-jammy.rootfs.tar.gz --version 2
# inside it (wsl -d Ubuntu-Airflow -u root): python3 -m venv /opt/airflow-venv, then
/opt/airflow-venv/bin/pip install "apache-airflow==3.1.8" apache-airflow-providers-standard \
    --constraint https://raw.githubusercontent.com/apache/airflow/constraints-3.1.8/constraints-3.10.txt
```
Tested with Airflow 3.1.8 on Python 3.10 (Ubuntu 22.04). The DAG files import `airflow.sdk` and the standard provider (3.x) with a fallback to the 2.x imports.

### Start, trigger, observe
```
# start (blocks; UI at http://127.0.0.1:8080, admin password in /opt/airflow_home/simple_auth_manager_passwords.json.generated)
wsl -d Ubuntu-Airflow -u root -- bash "/mnt/c/.../Aniruddh_Healthcare/scripts/airflow_standalone.sh"
# MySQL and (optionally) the API must be running on Windows; set HC_RETRY_DELAY_SECONDS=20 first to shorten retries in a demo
airflow dags reserialize ; airflow dags list ; airflow dags list-import-errors     # both DAGs listed, no import errors
airflow tasks test healthcare_incremental_etl scan_for_new_files 2026-10-09        # one task in isolation
airflow dags unpause healthcare_incremental_etl ; airflow dags trigger healthcare_incremental_etl
airflow dags list-runs healthcare_incremental_etl ; airflow tasks states-for-dag-run <dag_id> <run_id>
```
Task logs: `/opt/airflow_home/logs/dag_id=<dag>/run_id=<run>/task_id=<task>/attempt=<n>.log` (also the Logs tab in the UI). Check the result in the app's **Pipeline Runs** page or `SELECT * FROM pipeline_runs ORDER BY run_id DESC`.

### How it is wired (and why)
* The tasks call the **Windows** project Python from WSL (`.../venv/Scripts/python.exe`, WSL interop), so no project code runs inside the Airflow environment and the database stays on the Windows `127.0.0.1`. Set `HC_PROJECT_ROOT` / `HC_PYTHON` if the project lives elsewhere.
* `AIRFLOW_HOME` is `/opt/airflow_home` on the Linux filesystem, not `./airflow_home`: SQLite locks unreliably on the Windows mount. (`airflow_home/` stays git-ignored in case you use it.)
* Modules run from `src/` (`cd src && python -m etl.pipeline --scan`) because an inline `PYTHONPATH=src` is **not** forwarded from WSL to a Windows `python.exe` (found by running it: `No module named 'etl'`). Scripts add `src/` to their own path.
* DAG files import nothing from the project and touch no database at import time, so they parse instantly.

### Demonstrated runs (2026-10-09, dev database)
| Step | Result |
|---|---|
| `airflow dags list-import-errors` | none; both DAGs listed |
| Unpause `healthcare_incremental_etl` | exactly one scheduled run for the latest hour (`catchup=False`), no backlog |
| First run (before the `python -m` fix) | `run_etl` failed three times (retries 20 s apart), `check_quality` and `record_summary` "upstream_failed", nothing loaded: the failure path, for an accidental reason |
| Trigger with `encounters_batch_002.csv` waiting | run 8: 5,089 loaded, active encounters 91,566 -> 96,655 |
| Trigger again immediately | success, **no new pipeline run**, count unchanged, log "no new files: nothing to load (successful no-op)" |
| Copy held-back batch 004 into `data/incoming`, trigger | run 9: 5,088 loaded, active 101,743; `verify_kpis.py` 88/88 still passes |
| `make_faulty_batch.py --severe` (30% bad rows), trigger | `run_etl` Try Number 3 then FAILED; DAG run `failed`; pipeline runs 10, 11, 12 FAILED ("reject ratio 0.300 exceeds the allowed 0.200"); `data/rejected/severe_faulty_batch_rejected.csv` written; **nothing loaded** (101,743 unchanged) |
| `healthcare_weekly_report` | success; 4 files in `data/reports/` and 4 `report_runs` rows (`triggered_by = airflow`) |
Screenshots: `docs/screenshots/20_` to `26_` (DAG list, task graphs for a success and a failure, run history, the app's Pipeline Runs page).

### Recover from a failed run
1. Open the failed run's `run_etl` log (UI or path above) or the app's Pipeline Runs / Data Quality pages: the error and the rule counts are there. A refused file has `data/rejected/<file>_rejected.csv` with a reason per row.
2. Fix or remove the file in `data/incoming` (a failed file is never marked done, so the same name can be re-dropped once corrected). Nothing from a failed file was loaded.
3. Trigger the DAG again (`airflow dags trigger healthcare_incremental_etl`) or clear the failed task in the UI. Loading is idempotent: files already loaded are skipped, so re-running is always safe.
4. A bad file left in `data/incoming` makes every hourly run fail until it is moved out; that is intended (it keeps the problem visible).

### Fallback scheduler (no Airflow needed)
`python scripts/scheduler.py` runs the same two jobs (`etl.jobs`) on the same schedules with APScheduler (`--once etl` or `--once reports` runs one job now). Trade-offs: no UI or task graph, a simple retry loop (2 retries, 2 minutes apart) instead of per-task retry history, and no catch-up (matching `catchup=False`). Both jobs were run for real: the ETL job as a clean no-op and the reports job wrote 4 files with `triggered_by = scheduler`. The Airflow DAGs remain the intended design.

## Common problems
* `ReferenceDataError`: run `python db/seed_reference.py`.
* Smoke test fails with a connection error: MySQL is not running (see step 1). Use `127.0.0.1`, not `localhost`, in the URLs.
* API will not start: `JWT_SECRET` is missing, shorter than 32 characters or a placeholder.
