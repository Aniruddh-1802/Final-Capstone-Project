# Healthcare Patient Management System

A local, end-to-end data system built on the UCI *Diabetes 130-US Hospitals (1999-2008)* research extract: ETL with data-quality rules, a MySQL database, a secured FastAPI service, a React dashboard and scheduled pipelines.

**Educational use only.** Admission and discharge dates in this system are **simulated** (the dataset has no dates), the data has **no hospital identifier**, and all findings are associations, never causes.

## Project Overview
The system ingests 101,766 hospital encounters of 71,518 diabetic patients in one initial and four incremental batch files, validates and cleans them, stores them in a normalised MySQL schema, and serves them through a role-protected REST API and a React dashboard. It also generates CSV and Excel reports, keeps an audit trail of every change, and is scheduled with Apache Airflow.

| Piece | Where |
|---|---|
| ETL (extract, transform, 13 quality rules, idempotent load) | `src/etl/` |
| Database (16 tables, views, indexes) | `src/app/models/`, `db/` |
| REST API (32 operations, JWT, three roles, audit) | `src/app/` |
| Dashboard and admin pages | `frontend/` |
| Scheduling | `src/airflow/dags/`, `scripts/scheduler.py` |
| Tests | `tests/`, `frontend/src/**/*.test.jsx`, `frontend/e2e/` |
| Documents | `design/`, `docs/`, `architecture/`, `presentation/` |

## Problem Statement
A hospital operations team holds a flat CSV of inpatient encounters with coded values, missing-value markers and no dates. They need to load new files repeatedly without double counting, reject or flag bad rows with evidence, query the data safely, and see readmission, length-of-stay and utilisation patterns, while sensitive attributes stay restricted by role.

## Business Objective
Answer four questions with defensible numbers: (1) the 30-day readmission rate and how it differs by group, (2) length of stay, (3) admission and readmission trends over (simulated) time, (4) medication, lab-test and prior-utilisation patterns associated with readmission. The readmission rate always uses *eligible* encounters (expired and hospice discharges removed) as its denominator: **0.113888** (11,314 / 99,343) on the full data, whereas dividing by all encounters would silently give 0.111177.

## Solution Summary
Dataset -> `prepare_batches.py` (adds simulated dates) -> ETL (extract, transform, quality, load; one transaction per file; file hash plus key check makes reloads harmless) -> MySQL (soft delete behind one view) -> FastAPI (authentication, role checks, audit in the same transaction, analytics in SQL, exports) -> React. Airflow runs the incremental load hourly and the reports weekly. See `architecture/Architecture_Diagram.pdf` and `design/Design_Document.pdf`.

## Technology Stack
Python 3.12 (3.11+ works), pandas 3, SQLAlchemy 2.0, PyMySQL, MySQL 8.4, FastAPI, Pydantic v2, bcrypt, PyJWT, pytest; React 19, Vite, Recharts, axios (Node 20+); Apache Airflow 3.1 in its own virtualenv (WSL2 on Windows). No Docker, cloud or CI/CD.

## Installation
Prerequisites: Python 3.11+, MySQL 8 (server running on `127.0.0.1:3306`), Node 20+. Commands are for Windows PowerShell; on Linux or macOS use `source venv/bin/activate` and forward slashes.

1. Clone the repository and open a terminal in its root folder.
2. Create the environment and install the packages:
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Get the data. Download *Diabetes 130-US Hospitals for Years 1999-2008* from https://archive.ics.uci.edu/dataset/296/diabetes+130-us+hospitals+for+years+1999-2008 (CC BY 4.0) and copy `diabetic_data.csv` into `data/raw/` (raw data is git-ignored). `IDs_mapping.csv` is already in `data/reference/`.

## Environment Setup
4. Create the databases and the least-privilege user: open `db/setup_database.sql`, replace both `CHANGE_ME` passwords with one password of your choice, and run it once as the MySQL administrator (`mysql -u root -p < db/setup_database.sql`). It creates `healthcare_db`, `healthcare_test` and the user `hc_app`.
5. Copy `.env.example` to `.env` and fill it in (this file is git-ignored):
   - `DATABASE_URL` and `TEST_DATABASE_URL`: use the `hc_app` password from step 4 (keep `127.0.0.1`, not `localhost`).
   - `JWT_SECRET`: a random string of at least 32 characters, for example `python -c "import secrets; print(secrets.token_urlsafe(48))"`. The API refuses to start without it.
   - `ADMIN_PASSWORD`, `CLINICAL_OPS_PASSWORD`, `ANALYST_PASSWORD`: demo passwords of at least 12 characters for the three users (if left empty, random ones are generated and printed once in step 7).
6. Check the setup: `python scripts/smoke_test.py` (expects PASS for Python, MySQL connection and a create/insert/select/drop round trip).

## Database Setup
7. Create the tables and seed the lookups and users (these scripts are safe to repeat):
   ```
   python db/seed_reference.py        # creates all 16 tables, loads the lookup tables from IDs_mapping.csv
   python db/seed_users.py            # one user per role (admin, clinical_ops, analyst), bcrypt-hashed
   python scripts/apply_views.py      # v_active_encounters and v_readmission_base
   ```
   The DDL is also available as `db/schema.sql` (generated from the models, `python scripts/export_ddl.py`), the four performance indexes as `db/indexes.sql` and the ERD as `docs/erd.png`.

## ETL Execution
8. Prepare the batch files (simulated dates, seed 42): `python scripts/prepare_batches.py` writes the initial batch and batches 001-002 to `data/incoming/` and keeps batches 003-004 in `data/held_back/` for incremental demonstrations.
9. Load (from the repository root):
   ```
   cd src
   python -m etl.pipeline --scan                       # loads every new file in data/incoming (initial batch: 81,412 rows, about 12 s)
   cd ..
   python scripts/verify_kpis.py                       # recomputes the KPIs in pandas from the raw CSV and compares SQL and API; expects "88/88 checks passed" (it compares only the encounters that are loaded, so it works at any stage)
   ```
   To load one file: `cd src && python -m etl.pipeline --file ../data/incoming/encounters_batch_001.csv`. Output is logged to `logs/etl.log`; every run is one row in `pipeline_runs`.
10. Add the rest of the data to see incremental loading: copy `data/held_back/encounters_batch_003.csv` and `..._004.csv` into `data/incoming/` and run `python -m etl.pipeline --scan` again (from `src`). Running it twice changes nothing (`SKIPPED_DUPLICATE_FILE` or "no new files"). After all five batches the database holds 101,766 encounters.
11. Failure demonstration: `python scripts/make_faulty_batch.py` writes `data/incoming/faulty_batch.csv` (injected faults); loading it quarantines the bad rows in `data/rejected/` with a reason per row. `--severe` makes a file with 30% bad rows, which is refused whole.

Quality rules DQ01-DQ13, the run table and recovery steps: `docs/data_contract.md` (section 8b) and `docs/runbook.md`.

## Running the API
12. Start the API (second terminal, from the repository root with the environment active):
    ```
    cd src
    uvicorn app.main:app --reload
    ```
    Swagger UI: http://127.0.0.1:8000/docs, health: http://127.0.0.1:8000/health. Log in with the form at `/auth/login` (or curl, below), then send `Authorization: Bearer <token>`; in Swagger use the Authorize button.

## Running the Frontend
13. Start the dashboard (third terminal):
    ```
    cd frontend
    npm install
    npm run dev
    ```
    Open http://127.0.0.1:5173 and sign in as `admin`, `clinical_ops` or `analyst` with the passwords from step 5. The menu and buttons change by role; the API still enforces every permission. The Vite dev server proxies `/api` to the API on port 8000.

## Airflow Quick Start
Airflow does not run natively on Windows and its dependencies conflict with FastAPI, so it lives in its own environment. The two DAGs are `src/airflow/dags/healthcare_incremental_etl.py` (hourly: scan, load, quality check, summary) and `healthcare_weekly_report.py` (Mondays 06:00). Full install, start, trigger and recovery steps, with the runs that were demonstrated: `docs/runbook.md`. In short, inside WSL2: install Airflow 3.1 into `/opt/airflow-venv` with the official constraints file, run `scripts/airflow_standalone.sh`, open http://localhost:8080, unpause both DAGs. Without Airflow the same jobs run with `python scripts/scheduler.py` (or once: `--once etl`, `--once reports`).

## Sample API Requests
Real calls against the loaded database (more in `docs/API_Documentation.pdf`; `$TOKEN` is the bearer token).
```
# 1. log in (token valid 60 minutes)
curl -X POST http://127.0.0.1:8000/auth/login -d "username=admin" -d "password=<your password>"
#    {"access_token": "eyJ...", "token_type": "bearer", "expires_in": 3600}

# 2. headline KPIs (the rate uses ELIGIBLE encounters; dates are SIMULATED)
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/analytics/summary
#    {"data": {"total_encounters": 101766, "unique_patients": 71518, "avg_length_of_stay": 4.395987,
#              "eligible_encounters": 99343, "readmitted_30d": 11314, "readmission_rate_30d": 0.113888,
#              "any_readmission_rate": 0.471256, ...},
#     "meta": {"denominator": "eligible encounters (...)", "dates_simulated": true, ...}}

# 3. filtered, sorted, paged list: oldest patients readmitted within 30 days, longest stays first
curl -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/encounters?age_group=%5B90-100%29&readmitted=%3C30&sort_by=time_in_hospital&sort_dir=desc&page_size=2"
#    first item: encounter 60241242, admitted 2000-10-29, 14 days, "[90-100)", readmitted "<30"

# 4. the same call as an analyst returns the minimised view: no patient_nbr, race or gender in any item

# 5. an analyst calling a patient endpoint is refused
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/patients
#    403 {"error": {"code": "forbidden", "message": "...", "details": null}}
```
Creating and updating records (`POST /encounters`, `PUT /encounters/{id}`) with their audit entries are shown in `docs/API_Documentation.pdf`.

## Tests
```
pytest                          # backend: needs the healthcare_test database (step 4); takes about 10 minutes
pytest --cov=src                # with coverage
cd frontend && npm test         # 42 unit and component tests
node frontend/e2e/run.mjs       # real-browser run (needs Chrome, the API and the dev server running)
```
The test fixture refuses to run against any database whose name does not end in `_test`, so tests can never touch loaded data. Results, coverage and known gaps: `docs/test_report.md`.

## Project Structure
```
architecture/   Architecture_Diagram.pdf / .jpeg / .png
design/         Design_Document.pdf (+ .md)
docs/           API_Documentation.pdf, Dataset_Details.pdf, data_contract.md, decision_log.md, runbook.md,
                performance_notes.md, test_report.md, rubric_self_audit.md, ai_usage_log.md, erd.png, screenshots/
presentation/   Project_Presentation.pptx / .pdf, demo_video_link.txt
src/app/        FastAPI service (models, schemas, services, routers, permissions)
src/etl/        extract, transform, quality, load, pipeline, jobs, reports
src/airflow/    DAGs
db/             schema.sql, indexes.sql, setup_database.sql, seed scripts, queries/ (views and KPI SQL)
scripts/        prepare_batches, verify_kpis, scheduler, diagrams and document builders, perf tools
frontend/       React + Vite application, Vitest tests, e2e/ browser run
tests/          pytest suite (etl/, api/, schema, KPIs, indexes)
data/           raw/ (git-ignored), reference/, incoming/, held_back/, rejected/, reports/ (git-ignored)
```

## Limitations
- **Dates are simulated** (seeded, labelled everywhere); trends are illustrative, not clinical findings.
- **No hospital identifier** exists in the data, so no hospital-level analysis is made.
- Observational 1999-2008 data: associations only, no causal or predictive claims.
- `medical_specialty` (49%) and `payer_code` (40%) are heavily missing.
- Two analytics queries (readmission by age group, top drugs) take 0.6-0.8 s because they read every encounter; no summary table was built (see `docs/performance_notes.md`).
- Local only: no cloud, Docker or CI/CD; Airflow is demonstrated on 3.1 in WSL2 only; not tested on a real tablet or with a screen reader.
- Demo passwords are local and must be changed for any other use.

## Acknowledgements
Dataset: Strack, DeShazo, Gennings, Olmo, Ventura, Cios and Clore (2014), *Impact of HbA1c Measurement on Hospital Readmission Rates: Analysis of 70,000 Clinical Database Patient Records*, BioMed Research International; UCI Machine Learning Repository, DOI 10.24432/C5230J, CC BY 4.0.

AI assistance: this project was built with Claude Code (Anthropic) as a pair-programming assistant, guided by the course lab guide. Every use, what was accepted, what was rejected and how each result was verified is recorded in `docs/ai_usage_log.md`; design decisions are in `docs/decision_log.md`.
