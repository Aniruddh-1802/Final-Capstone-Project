# Rubric self-audit (100 marks)

Marks are my own honest estimate against the deck's rubric (page 8), strict on anything not demonstrated. Evidence is a file or a screen you can open.

| Area | Max | My mark | Evidence | What is missing or weak |
|---|---|---|---|---|
| Data ingestion and ETL | 15 | 14 | `src/etl/` (extract, transform, quality, load, pipeline, jobs); five batches loaded with reconciliation (`docs/runbook.md` run table, screenshot `10_pipeline_runs.png`); idempotency tests (`tests/etl/test_pipeline.py`); Airflow DAGs and demonstrated runs (`docs/screenshots/20_` to `26_`); hard-kill test in `docs/decision_log.md` | Airflow tested on 3.1 in WSL2 only and triggered from the command line; no streaming or API source (not required) |
| Data cleaning and quality | 10 | 9 | 13 rules DQ01-DQ13 (`docs/data_contract.md` 8b); quarantine with reasons (`data/rejected/`, Data Quality page `11_data_quality.png`); faulty batch rejected row for row (`tests/etl/test_quality.py`); profiling findings (`docs/data_profile.md`) | Genuine data rejects zero rows, so several rules are proven only on the injected faulty batch; imputation deliberately not done |
| Database and SQL | 15 | 14 | 16-table schema and ERD (`docs/erd.png`, `db/schema.sql`); views and 14 named KPI queries (`db/queries/`); four indexes proven by EXPLAIN before and after (`docs/performance_notes.md`); soft delete through one view; seed scripts | Two analytics queries remain 0.6-0.8 s (documented, summary table rejected for now) |
| Python programming | 10 | 9 | Typed, documented modules with logging and no `print`; pure transform functions; single permission constant; shared validation between ETL and API; scripts under `scripts/` | A few long service modules; the profiling script is untested |
| REST API and CRUD | 15 | 14 | 32 operations (`docs/API_Documentation.pdf`, Swagger `/docs`); JWT and three roles; CRUD with validation; filter, sort, page, search; uniform errors; audit in the same transaction (`tests/api/`); role verification table (`docs/role_verification.md`) | No refresh tokens or rate limiting (documented trade-offs) |
| Analytics and KPIs | 10 | 9 | Six analytics endpoints and nine dashboard charts; eligible-denominator rule enforced and checked three ways (`scripts/verify_kpis.py`, 88 checks); small-n flags; careful wording | Dates simulated, so trends are illustrative; no statistical testing (associations only, stated) |
| Dashboard and visualisation | 10 | 9 | React app with role-aware pages (`docs/screenshots/01_` to `18_`, `docs/dashboard_map.md`); filters, tables, exports, simulated-dates banner; authenticated downloads; 71-check browser run | Not tested on a real tablet or with a screen reader |
| Testing and logging | 5 | 4 | 315 backend tests (94% coverage), 42 UI tests, 71 browser checks (`docs/test_report.md`); deliberate-bug checks; log and secret scan; rotating logs with request ids | CLI entry point and profiling script outside pytest; gaps ranked in the test report |
| Architecture and design | 5 | 4 | `architecture/Architecture_Diagram.pdf`; `design/Design_Document.pdf` (decisions, trade-offs, limitations); `docs/decision_log.md` | The diagram shows components, not deployment (local only by design) |
| Documentation and presentation | 5 | 4 | README (fresh-clone verified), API documentation, dataset details, runbook, deck (`presentation/Project_Presentation.pptx` and PDF), demo script | **Demo video not yet recorded** (`presentation/demo_video_link.txt` says so); the rehearsal with a stopwatch has to be done by the presenter |
| **Total** | **100** | **90** | | |

## Checks behind the marks
- Fresh clone (new folder, new virtualenv, new databases) followed the README: smoke test, seeding, five batch loads with a repeat scan that did nothing, 88 of 88 KPI checks, API and dashboard start, 42 of 42 UI tests, 71 of 71 browser checks, 314 passed and 1 skipped backend tests (the skip passes once README step 11 has run).
- Secrets: the real database password, JWT secret and MySQL root password were searched in every staged file before the first commit: 0 hits; `.env` and raw data are not tracked.
- Limitations are stated in the README, the Design Document, Dataset Details and the deck: simulated dates, no hospital identifier, observational data.

## Before submitting (things only the presenter can do)
1. Record the 5-7 minute video and put its private link in `presentation/demo_video_link.txt`.
2. Rehearse `presentation/demo_script.md` twice with a stopwatch and prepare answers from Appendix F.
3. Push the repository to GitHub, confirm access for the organisers and send them the repository link, the optional video link and team details.
4. Change the demo passwords if the repository or the database is shared.
