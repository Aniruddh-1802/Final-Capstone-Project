# Test report

Replaces the "Evaluation Report" item of the submission guidelines (this project has no GenAI component). All numbers were produced on **2026-10-09 from a fresh clone** of the repository (new folder, new virtualenv, new databases `healthcare_fresh` and `healthcare_fresh_test`) by following the README; nothing here is estimated.

## 1. How to run
```
pytest                          # backend, needs healthcare_test (README step 4); about 11 minutes
pytest --cov=src --cov-report=term-missing
cd frontend && npm test         # 42 unit and component tests
node frontend/e2e/run.mjs       # 71 real-browser checks (Chrome, API on :8000, dev server on :5173; E2E_*_PASSWORD variables)
python scripts/verify_kpis.py   # 88 checks: SQL = API = pandas on the raw CSV
```
Safety: the database fixture (`tests/conftest.py`) refuses to run unless `TEST_DATABASE_URL` names a schema ending in `_test` that differs from the development database, so a test can never clean up loaded data.
One test reads `data/incoming/faulty_batch.json`, which exists after `python scripts/make_faulty_batch.py` (README step 11); without it that single test is skipped.

## 2. Results
| Suite | Result |
|---|---|
| Backend (pytest) on the fresh clone | **314 passed, 1 skipped** in 11 min 36 s (the skip needs `faulty_batch.json`; run on its own after `make_faulty_batch.py`, the file passes: 21 of 21) |
| Backend on the development checkout (earlier run, before the log-hygiene test was added) | 314 passed in 10 min 12 s |
| Audit and log-hygiene change, targeted | 99 passed (patients, audit, listing, log hygiene) |
| Frontend (Vitest) on the fresh clone | 42 passed, 8 files |
| Real-browser run (headless Chrome, three roles) on the fresh clone | 71 of 71 checks passed |
| KPI cross-check (`verify_kpis.py`) on the fresh clone, all five batches | 88 of 88 checks passed |

**Independence from leftover data.** The suite passed from a completely empty database (the fresh clone) and repeatedly on the development test schema without manual cleanup; the loaded development database (101,766 encounters) was unchanged after the runs.

## 3. Coverage (line coverage of `src/`, pytest-cov)
**94% overall: 2,475 statements, 146 missed.** 40 of 57 files are at 100%. Files below 100%:

| File | Cover | What is not covered by pytest |
|---|---|---|
| `etl/profile.py` | 0% | the one-off profiling script that produced `docs/data_profile.md` (run by hand, output reviewed) |
| `etl/pipeline.py` | 88% | the command-line entry point (`main`, `configure_logging` wiring); it is exercised by every real load, the hard-kill test and the Airflow runs, but not by pytest |
| `app/services/encounters.py` | 98% | 4 defensive branches |
| `app/services/patients.py` | 95% | the 409-after-rollback branch (lines 56-58) |
| `etl/extract.py` | 94% | three error branches of the ID-mapping parser |
| `app/services/admin.py` | 94% | duplicate-username race branch |
| `app/database.py`, `app/middleware.py`, `utils/logging_config.py`, `app/security.py`, `app/schemas/*`, `app/services/query_helpers.py`, `app/services/audit.py`, `etl/load.py`, `etl/quality.py`, `etl/reports.py` | 90-99% | single defensive lines |

Coverage is not the goal. The rules that matter were checked **by name** (section 5): the eligible denominator, idempotency, rollback, soft delete, RBAC and audit atomicity each have tests that fail when the rule is broken.

## 4. Deliberate-bug checks (tests must fail when the code is wrong)
| Mutation | Result |
|---|---|
| Every encounter counted as readmission-eligible (`ELIGIBLE` in `analytics.py` replaced by an always-true condition) | **6 tests fail**: summary hand calculation, summary equals headline SQL, readmissions by age group, by other groups, medications and utilisation |
| Race and gender copied back into the patient audit snapshot | **2 tests fail**: the log-hygiene test and the patient audit test |
| (Earlier) an unprotected route added | the "every route needs a token" test flags it |
| (Earlier) audit write or commit forced to fail | no data row and no audit row remain, for create, update and delete |

Both files were restored byte-for-byte after the mutations (hash compared).

## 5. The 20 silent-failure traps of the guide (Appendix B)
| # | Trap | Evidence (test or recorded manual check) |
|---|---|---|
| 1 | Pandas turns "None" into missing | `test_read_batch_missing_markers_and_none_value`, `test_lab_none_survives_build_tables`; profile shows 96,420 / 84,748 would be lost |
| 2 | Rate over all encounters | `test_summary_matches_hand_calculation`, `test_summary_equals_the_l7_headline_sql`, `test_expired_group_has_no_eligible_encounters_and_null_rate`, `verify_kpis.py` (prints the wrong-denominator value), mutation in section 4 |
| 3 | Encounters counted as patients | hand-built fixture has one patient with three encounters; headline `unique_patients` checked in `test_headline_matches_pandas_on_fixture` and `verify_kpis.py` |
| 4 | Soft-deleted rows leak | `test_soft_delete_drops_headline_by_exactly_one_and_undo_restores`, `test_deleted_patient_hides_all_their_encounters`, `test_soft_deleted_rows_and_deleted_patients_never_count`, `test_soft_deleted_encounters_are_not_exported` |
| 5 | Simulated dates shown as real | `test_every_response_says_dates_are_simulated_and_names_the_denominator`; UI banner in the Vitest dashboard test and the browser run |
| 6 | Reload or renamed copy double counts | `test_same_file_twice_is_skipped_duplicate`, `test_renamed_reordered_copy_skips_all_rows`; fresh-clone repeat scan loaded nothing |
| 7 | `INSERT IGNORE` hides errors | not used anywhere in `src/` (searched); `test_first_run_loads_and_reconciles`, `test_reconciliation_failure_rolls_back` |
| 8 | Commit per chunk | `test_forced_failure_mid_load_leaves_nothing`; manual hard-kill run recorded in `docs/decision_log.md` (L6) |
| 9 | Age bracket sorted as text | `test_derive_age_order`, `test_readmissions_by_age_group_in_clinical_order_with_small_n` |
| 10 | ICD-9 codes converted to numbers | `test_transform.py` asserts `V57` and `E909` survive; `test_dq06_icd_format_corrects_without_rejecting`; ICD prefix search tests |
| 11 | "No" medication rows stored | `test_medications_dimension_and_no_rows_for_unprescribed` |
| 12 | Join fan-out inflates counts | `test_group_counts_always_add_up_to_the_filtered_total` |
| 13 | Unstable paging, unbounded page size, free-text sort | `test_paging_walks_every_row_once_in_the_requested_order`; parametrised invalid sort and page-size cases in `test_listing.py` (including `encounter_id;DROP TABLE x`) |
| 14 | Function on an indexed column | `test_indexes.py` (indexes exist, apply is idempotent); EXPLAIN plans naming each key in `docs/performance_notes.md` (manual evidence) |
| 15 | Stale responses overwrite newer filters | Vitest "ignores a slow response for an OLD filter that arrives after the newest one"; browser run changes the filter six times in half a second and compares with the API |
| 16 | Download with `window.open` | browser check "Excel report downloads through the UI with authentication (blob, no token in URL)" |
| 17 | Hiding buttons treated as security | `docs/role_verification.md` (UI versus direct API call per role and action, all agree); `test_wrong_role_is_403_right_role_is_200`, `test_role_matrix_for_patients`, `test_permission_matrix_in_code_matches_the_contract_document` |
| 18 | Airflow installed in the project venv | separate virtualenv in WSL2 (`docs/runbook.md`); `test_dag_files_compile_and_are_thin`; the API suite passed after the install |
| 19 | Secrets or raw data committed | `.gitignore` written first; before the first commit the real database password, JWT secret and MySQL root password were searched in every staged file (0 hits); no CSV other than the lookup, the 500-row sample and a 30-row fixture is tracked (manual check, 2026-10-09) |
| 20 | Tests pointed at the development database | fixture refuses non-`*_test` schemas (`tests/conftest.py`); the development row count was identical before and after the suite (manual check) |

## 6. Logs, secrets and error responses
- **Scan of all log files** (`logs/`, about 1.7 MB) for JWTs, bearer tokens, `password=` values, bcrypt hashes, `JWT_SECRET`: **0 matches**. `race` or `gender` appear only in `profile.log`, the L1 profiling script's aggregate value counts of the raw file (no per-patient rows).
- **`tests/api/test_log_hygiene.py`** drives good and bad logins, patient create/update/delete, invalid bodies, a forbidden call, an export and a forced 500 while capturing every log record at DEBUG; it fails if any password, token, hash, race value or demographic field name appears in the logs, the whole `audit_logs` table or any error body.
- **Finding fixed during this lab:** patient audit rows stored the before and after values of race and gender. The audit now records only that demographics are set and which field changed (`changed_fields`), never the values; the old synthetic audit rows in the development database were scrubbed. A test pins the new behaviour and the mutation in section 4 proves it.
- **Stack traces and SQL:** every error uses the single contract body; a forced `ZeroDivisionError` returns a generic 500 with no exception name, traceback or file/line; a database outage returns a generic message (`test_errors.py`). No endpoint was found that can return SQL text: SQL is built with bound parameters and sort columns come from a whitelist.
- **Swallowed exceptions and prints:** none of the latter in `src/`; the single broad `except` (in `pipeline.py`) is deliberate: it logs the full traceback with `log.exception`, closes the run as FAILED with the error message, loads nothing, and the command-line exit code becomes 1, so the failure is neither hidden nor left as a RUNNING row.

## 7. Missing tests ranked by risk (and what was done)
| Risk | Gap | Status |
|---|---|---|
| HIGH | Secrets or demographics in logs, audit trail or errors | **Added** (`test_log_hygiene.py`); found and fixed the audit leak |
| HIGH | Eligible-denominator regression | covered by six tests; mutation proves it |
| MEDIUM | `etl.pipeline.main` (CLI path) has no pytest test | open; exercised by the hard-kill test, every real load and Airflow runs |
| MEDIUM | Guard that the test fixture refuses a non-test database | open; manual check recorded above |
| LOW | `etl/profile.py` untested | open; one-off script with reviewed output |
| LOW | Concurrent duplicate create (two requests at once) | open; the 409 branch is covered sequentially |
| LOW | Accessibility, tablet layout, screen reader | open; not tested |
| LOW | Opening exported `.xlsx` in Excel itself | open; files are validated with openpyxl only |
| LOW | Airflow 2.x compatibility | open; only 3.1 was run (the DAGs fall back to 2.x imports but this was not tested) |
| LOW | Load test beyond 100k rows | open; performance measured with 101,766 encounters plus 300,000 audit rows only |

## 8. What is mocked and what is not
Nothing in the database layer is mocked: loaders, analytics, RBAC, audit and soft delete are tested against the real MySQL test schema, because a mocked database passes even when the SQL is wrong. The Vitest component tests mock only the API client; the browser run then checks the real UI against the real API.

## 9. Known gaps
Section 7 lists them. In short: no real tablet or screen-reader test; the CLI entry point and the profiling script are outside pytest; Excel itself was not used to open the reports; Airflow was verified on 3.1 in WSL2 only and triggered from the command line rather than by hand in the UI.
