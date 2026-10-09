# AI usage log

Four lines per lab: what I asked; what Claude produced; what I validated myself; what I changed or rejected and why.

## L0 - Environment, repository, project context
- Asked: scaffold the repo (tree, config, logging, smoke test, README skeleton) following the guide's L0 prompt.
- Produced: CLAUDE.md, config loader, logging utility, smoke test, README skeleton, `db/setup_database.sql`, `.env.example`.
- Validated: CLAUDE.md typo fixed on review (`na_values` had a stray quote); `config.py` project-root path corrected (`parents[2]`). Smoke test passes against a local MySQL 8.4.9 (portable install in `C:\Users\reach\mysql`, outside the repo) as `hc_app`, and `hc_app` sees only `healthcare_db` and `healthcare_test`. **Still to do by me:** stop MySQL and re-run the smoke test to see a clear failure; install git and confirm no CSV/`.env` is staged.
- Changed/rejected: dataset was downloaded straight from the UCI zip into `data/raw` and `data/reference` (file renamed `IDS_mapping.csv` -> `IDs_mapping.csv`); git is not installed so the "no CSV/.env tracked" check is pending.

## L1 - Profile the dataset
- Asked: profile the real files and report measured numbers.
- Produced: `src/etl/profile.py` and `docs/data_profile.md` (eight findings, column decisions, mapping-file layout).
- Validated: `<30` count agrees between `value_counts` and a boolean mask (11,357); 71,518 patients vs 101,766 encounters; `None` behaviour compared default vs contract read. **Still to do by me:** re-run the script, check the column list against the CSV header, and write your own first profiling pass to compare.
- Changed/rejected: the guide wanted the student to write the first profiling code; Claude wrote it all at the user's request. An initial claim that age brackets sort wrongly as text was wrong and removed (they sort correctly here; `age_order` is kept for robustness).

## L3 - Schema, models, seeding
- Asked: implement the agreed ERD as SQLAlchemy 2.0 models, DDL export, reference/user seeding and schema tests.
- Produced: `src/app/models/*`, `database.py`, `scripts/export_ddl.py`, `db/seed_reference.py`, `db/seed_users.py`, `etl.extract.read_id_mappings`, `tests/conftest.py`, `tests/test_schema.py`, `db/schema.sql`.
- Validated: 11 schema tests pass on `healthcare_test`; seed scripts run twice with unchanged row counts (8/25/30 reference rows, 3 users); exactly ids 11, 13, 14, 19, 20, 21 flagged; `SHOW CREATE TABLE encounters` read against the ERD; `schema.sql` loaded into an empty scratch database gave 16 tables. **Still to do by me:** try an orphan insert in the MySQL shell and `git grep` for the seeded passwords once git exists.
- Changed/rejected: first seed run used the wrong env-var prefix (`ADMINISTRATOR_PASSWORD` instead of the documented `ADMIN_PASSWORD`) and a test caught it; fixed. Generated passwords were printed to the terminal once (they appeared in this session's output) - change them via the `*_PASSWORD` variables in `.env` and re-seed on a fresh database before any real use.

## L4 - Extract and transform
- Asked: simulated batch files, `read_batch`, pure transforms, fixture and tests, following the L4 prompt.
- Produced: `scripts/prepare_batches.py`, `etl/extract.py`, `etl/transform.py`, `tests/fixtures/mini_diabetic.csv` (30 rows built by a one-off generator), `tests/etl/test_transform.py`.
- Validated: batch generation run twice gives identical file hashes; on the real initial batch encounters = outcomes = 81,412 input rows, patients = 58,782 distinct `patient_nbr`, non-"No" medication cells in the raw file (95,251) = rows built, ineligible rows (1,901) = expired/hospice count in the raw file, V/E codes stay strings. **Still to do by me:** compare three random encounters row by row against the CSV by hand.
- Changed/rejected: my first fixture tests compared ids as strings, but pandas reads them as integers - fixed in the tests; an expected `any_readmission` count of 5 was wrong (6) - corrected after counting the fixture.

## L5 - Data-quality rules
- Asked: rules DQ01-DQ13, quarantine, file-level policy, faulty-batch generator, tests.
- Produced: `etl/quality.py`, `scripts/make_faulty_batch.py`, `tests/etl/test_quality.py`, `data/rejected/faulty_batch_rejected.csv`.
- Validated: genuine batches (initial, 001, 003) reject 0 rows; faulty batch rejects exactly 23 rows (3/5/5/5/5 by rule) and corrects 5 ICD codes; independent one-line pandas counts (99 dispositions, negative stays, blank ids, duplicate ids) match; 48 tests pass. **Still to do by me:** open the faulty CSV in an editor and find two injected faults by eye.
- Changed/rejected: a strict 3-digit ICD rule would have "corrected" 5,732 real codes - loosened after profiling; a pandas 3 `astype(str)` quirk produced empty reasons for DQ01 and was fixed; DQ10 was narrowed so one fault trips one rule.

## L17 - Scheduled pipelines with Airflow
- Asked: two DAGs, a quality-check script, weekly report job, runbook, and a fallback scheduler, checked against the Airflow version actually installed (3.1.8, Python 3.10).
- Produced: `etl/jobs.py`, `scripts/{scan_incoming,check_latest_run,run_weekly_reports,scheduler,airflow_standalone.sh}`, `src/airflow/dags/*.py`, `make_faulty_batch.py --severe`, `tests/etl/test_jobs.py` (20 tests), `frontend/e2e/airflow_shots.mjs`, runbook section, screenshots 20-26.
- Validated: both DAGs listed by real Airflow with no import errors; `airflow tasks test` on the scan task; a triggered run loaded batch 002 (5,089 rows, total 91,566 -> 96,655); an immediate re-trigger was a clean no-op (no new pipeline run, log line says so); batch 004 dropped into `data/incoming` loaded (101,743) and `verify_kpis.py` still 88/88; a 30%-bad file failed after three attempts with three FAILED pipeline runs, a quarantine file and nothing loaded; the weekly DAG wrote 4 files and 4 `report_runs` rows; the fallback scheduler's two jobs ran for real. **Still to do by me:** read the task logs yourself and trigger a run from the Airflow UI, not only the CLI.
- Changed/rejected: my first DAG commands used an inline `PYTHONPATH`, which WSL does not forward, so the first scheduled run failed in `run_etl` (fixed by running modules from `src/`); I also had to put the virtualenv on `PATH` for `airflow standalone`. Airflow 3.3.2 is current but I pinned 3.1.8 with its constraints file for a stable, supported install. I did not test Airflow 2.x (the fallback imports are untested).

## L14-L16 - React front end
- Asked: Vite app with auth and role-aware layout, the KPI dashboard, record management, admin pages and report downloads.
- Produced: `frontend/` (API client, auth context, guards, 12 pages and components, `useApi`/`useListPage` hooks, encounter form schema), 42 Vitest tests, `frontend/e2e/run.mjs`, `docs/dashboard_map.md`, `docs/role_verification.md` (generated from the run), 18 screenshots; backend addition `group_by=overall` for length of stay.
- Validated: 42 unit/component tests; production build; a headless-Chrome run against the real API and database with 71 checks passing: navigation per role, UI versus direct API status for 15 actions x 3 roles (all agree), token in sessionStorage only and never in a URL, deleting the token lands on login, a tampered token is rejected and redirected, KPI cards equal the API, age groups in clinical order and sum to the total, six rapid filter changes settle on the last selection, an invalid length of stay is shown under its field without calling the API, a server 422 lands on the Patient number field, create/edit/delete with the audit log showing exactly CREATE, UPDATE, DELETE and the changed fields only, an Excel report downloaded through the UI, the 413 cap message shown. **Still to do by me:** use the app by hand for ten minutes and read the screenshots critically; I did not test on a real tablet or with a screen reader.
- Changed/rejected: my first e2e run reported two failures that were my test's fault (a history endpoint probed for analysts; Vite's own `/src/api/` files counted as API calls), a race (clicking Edit before the dialog loaded) and leftover records from a crash; a third issue was real: Vite bound to IPv6 only. The screenshots exposed overlapping chart labels and awkward checkbox captions, fixed afterwards.

## L12 - Indexes and query optimisation
- Asked: measure the frequent queries, propose the smallest justified index set, prove it, record the write cost.
- Produced: `scripts/perf_seed_audit.py`, `scripts/perf_measure.py`, `scripts/apply_indexes.py`, `db/indexes.sql`, model index definitions, the `NOT EXISTS` view rewrite, `tests/test_indexes.py`, `docs/performance_notes.md` (generated from the captured JSON).
- Validated: before / view-only / view+indexes timings with plans on a 101,766-encounter database; each index named in its plan; drop-one-index proof; one index (audit username+created_at) rejected because dropping it changed nothing; write cost +7%; KPI verification still 88/88 on the dev database after the view change. **Still to do by me:** run the EXPLAINs yourself in the MySQL shell and explain the composite-index column order without notes.
- Changed/rejected: my first "view only" result was wrong because the view change had silently failed (a byte-order mark; errors hidden by `2>$null`); redone with errors visible. The first baseline (Q1 38 ms) was later 353 ms after `ANALYZE TABLE` flipped the plan; both are reported. Q4/Q7 remain slow and are documented, not hidden.

## L13 - Reports and exports
- Asked: report generator (CSV/Excel), export endpoints with role rules, history, audit and tests.
- Produced: `etl/reports.py`, `routers/reports.py`, `tests/api/test_reports.py` (27 tests), sample files in `data/sample_data/` and `data/reports/`.
- Validated: files round-trip through pandas and openpyxl (sheets, numbers as numbers, real dates, styled headers); report totals equal `/analytics` for the same filters; encounter-export rows equal the list API total; header and values contain no demographics; cap returns 413 with a message; analyst gets 403; report_runs and EXPORT audit rows exist; live on the real database the workbook Summary equals `/analytics/summary` (91,566 encounters, rate 0.114258). **Still to do by me:** open the workbook in Excel or LibreOffice and look at it.
- Changed/rejected: two loose assertions of mine (`or True`, a pointless walrus) were replaced; an ICD-code check now proves codes stay text in the export.

## L9 - CRUD for patients and encounters with audit
- Asked: schemas, services, routers, audit service and tests following the L9 prompt.
- Produced: `schemas/{patients,encounters,common}.py`, `services/{patients,encounters,audit}.py`, `routers/{patients,encounters}.py`, `tests/api/{test_patients,test_encounters,test_audit}.py`.
- Validated: 52 tests (13 patients, 31 encounters, 8 audit); rollback proofs (forced audit failure and forced commit failure leave no data and no audit row); over real HTTP on the real database: create/update/delete of an encounter gives exactly three audit rows whose before/after differ only in the changed fields and derived flags; a body with `readmitted_30d: true` and `readmitted: "NO"` is stored false; analyst gets 403 on `/patients/1` and no `patient_nbr` on `/encounters/{id}`; the active count changes by exactly one on create and again on delete. **Still to do by me:** repeat the Swagger click-through and read the audit rows in the MySQL shell, and decide whether audit should also record failed attempts.
- Changed/rejected: Pydantic model validators gave errors at `loc: ["body"]`, so cross-field rules moved to the service for field-level 422s; `dates_simulated` was silently dropped by `exclude_unset` until set explicitly; one of my tests logged in while `Session.commit` was patched to fail (test bug).

## L10 - Filtering, sorting, pagination, search, admin and reference endpoints
- Asked: query helpers, filters, whitelisted sorting, stable paging, admin lists, users, reference lookups.
- Produced: `services/{query_helpers,views,admin}.py`, `routers/{admin,reference}.py`, `schemas/admin.py`, `docs/api_parameters.md`, `tests/api/test_listing.py` (77 cases).
- Validated: every filter against an independent pandas oracle; inclusive date boundaries; every sort column in both directions walked page by page against the oracle order; injection strings give 422; live check that pages of 10 over a 266-row filtered result equal the SQL id set and the API total equals `SELECT COUNT(*)`. **Still to do by me:** explain the whitelist/tiebreaker design without notes.
- Changed/rejected: a filter test's last assertion was vacuous (`... or filters`) and was replaced with an exact check; I did not implement user deactivation endpoints (cut list).

## L11 - Analytics endpoints
- Asked: six read-only endpoints, shared filters, response envelope, hand-calculated fixture.
- Produced: `services/analytics.py`, `routers/analytics.py`, `schemas/analytics.py`, `tests/api/test_analytics.py` (26 tests), API checks added to `scripts/verify_kpis.py`.
- Validated: 40-row fixture with every number worked out by hand in the test file (30-day rate 5/36 = 0.138889, not 5/39); API summary equals the L7 SQL; group counts add up for every `group_by` and filter set; `verify_kpis.py` 88 of 88 against pandas on the real data. **Still to do by me:** recompute two of the fixture numbers on paper.
- Changed/rejected: MySQL `ONLY_FULL_GROUP_BY` rejected my first insulin ordering (sorted in Python instead); `COALESCE` on an ENUM column made SQLAlchemy reject the value 'No' (typed as String); AVG precision needed a `Numeric` cast; a test asserted empty `meta.filters` although the endpoint rightly echoes `granularity`/`group_by`.

## L6 - Load, incremental processing, run logging
- Asked: loader, incremental helpers, pipeline with run records and CLI, tests, and the five-run demo on real data.
- Produced: `etl/load.py`, `etl/incremental.py`, `etl/pipeline.py`, `tests/etl/test_load.py`, `tests/etl/test_pipeline.py`, `docs/runbook.md`.
- Validated: 17 new tests pass including a forced mid-load failure (zero rows left) and a reordered-copy run (all rows skipped); on real data the table counts equal the transform counts (86,501 encounters after runs 1-2; 91,566 after run 5), distinct encounter ids = encounters, outcomes = encounters, loaded rows across successful runs add up to 91,566. **Still to do by me:** kill the process mid-load on the 81k-row file and check the database.
- Changed/rejected: none needed in code; one decision of mine - a file refused at the threshold counts all rows as rejected so the run reconciles (the guide does not specify this).

- Follow-up manual checks (done, session of 2026-10-08): hard-killed the CLI mid-load on the test schema (rolled back fully, retry loaded 81,412); stopped MySQL and confirmed `/health` 503, login 500 with no SQL text, smoke test fails in 2.6 s, then recovery after restart; sent the exact request Swagger's Authorize button sends and used the token on `/auth/me`. These found two real bugs in my code (empty pipeline log; stale RUNNING run) which are fixed and tested. One mistake of mine: a first attempt ran against the dev database because an environment variable did not persist between commands; it only added two SKIPPED_DUPLICATE_FILE rows (runs 6-7) and changed no data. Not done: clicking the Authorize button in a real browser.

## L7 - KPI queries and views
- Asked: two views, 14 named KPI queries, a pandas cross-check, and tests.
- Produced: `db/queries/views.sql`, `db/queries/kpi_queries.sql`, `app/services/kpi_sql.py`, `scripts/verify_kpis.py`, `scripts/apply_views.py`, `tests/test_kpis.py`, KPI table in the data contract.
- Validated: `verify_kpis.py` 59 of 59 PASS; soft-delete test drops the headline by exactly one; wrong-denominator difference measured (0.114258 vs 0.111548). **Still to do by me:** write the first three queries yourself (the guide's point) and explain each denominator aloud.
- Changed/rejected: first draft of `insulin_status` failed MySQL's ONLY_FULL_GROUP_BY (fixed by ordering on the alias); division truncated rates to 4 decimals (fixed with 1.000000 *); a first draft of one test had a vacuous `or True` assertion and was rewritten to exact values.

## L8 - FastAPI foundation
- Asked: app factory, JWT login, role dependency, uniform errors, request ids, health, tests.
- Produced: `app/main.py`, `security.py`, `deps.py`, `permissions.py`, `errors.py`, `middleware.py`, `routers/auth.py`, `routers/health.py`, `schemas/auth.py`, `tests/api/*`.
- Validated: 31 API tests pass; started uvicorn and used curl for health, 401, wrong-password, login and `/auth/me`; Swagger returns 200; the all-routes sweep was mutation-checked. **Still to do by me:** read `security.py` and `deps.py` line by line, try the Swagger Authorize button, and stop MySQL by hand to see `/health` go 503.
- Changed/rejected: my first "every route" test silently checked nothing because FastAPI 0.143 no longer lists included routes in `app.routes`; it now reads the OpenAPI spec and asserts it found endpoints.

## L2 - Contract, date simulation, schema design
- Asked: write the data contract, design and critique the schema, draw ERD and architecture v0.
- Produced: `docs/data_contract.md`, `docs/schema_design.md`, `docs/erd.mmd`/`erd.png`, `architecture/architecture_v0.png`, `scripts/make_diagrams.py`, decision-log entries.
- Validated: medication saving (94.4% "No", 120,054 prescribed cells) and eligible-rate numbers recomputed from the data; two questions (Q1, Q5) hand-traced into SQL. **Still to do by me:** challenge the design, and confirm no `race`/`gender` appear outside `patients`.
- Changed/rejected: a wrong "~35% kept" figure for medications was replaced with the measured 5.6%; the hospital table and extra normalisation were rejected (see decision log). The design was written by Claude, not by the student, so the review step is self-review.
