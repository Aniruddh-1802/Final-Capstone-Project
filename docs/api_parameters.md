# API parameter contract (feeds API_Documentation.pdf)

All endpoints except `POST /auth/login` and `GET /health` need `Authorization: Bearer <token>`. Errors always look like
`{"error": {"code", "message", "details"}}` (401, 403, 404, 409, 422, 500). Every list returns
`{items, total, page, page_size, pages, meta: {filters, sort_by, sort_dir, dates_simulated?}}`. **Admission and discharge dates are simulated.**

## Endpoint table
| Method and path | Roles (matrix key) | Notes |
|---|---|---|
| `POST /patients` | administrator, clinical_ops (`write_records`) | 201; 409 if `patient_nbr` exists (even soft-deleted); audited |
| `GET /patients` | administrator, clinical_ops (`view_patients`) | list, search |
| `GET /patients/{patient_nbr}` | same | 404 if missing or soft-deleted |
| `PUT /patients/{patient_nbr}` | `write_records` | partial; explicit `null` clears a field; audited |
| `DELETE /patients/{patient_nbr}` | administrator (`delete_records`) | soft delete; their encounters vanish from all reads; audited |
| `GET /patients/{patient_nbr}/encounters` | `view_patients` | same envelope and fields as `GET /encounters` |
| `POST /encounters` | `write_records` | 201; nested `diagnoses` (max 3) and `medications`; flags derived by the server; 409 duplicate; audited |
| `GET /encounters` | all roles (`list_encounters`) | analyst response has no `patient_nbr` / `source_batch_id` |
| `GET /encounters/{id}` | all roles | detail with diagnoses and medications; 404 if deleted |
| `PUT /encounters/{id}` | `write_records` | partial; merged state re-validated; flags re-derived; audited |
| `DELETE /encounters/{id}` | administrator | soft delete; audited |
| `GET /analytics/summary`, `/admissions-trend`, `/length-of-stay`, `/readmissions`, `/medications`, `/utilization` | all roles (`dashboards`) | see below |
| `GET /admin/audit-logs` | administrator (`view_audit`) | |
| `GET /admin/pipeline-runs`, `GET /admin/dq-issues` | administrator, clinical_ops (`view_pipeline`) | |
| `GET /admin/users`, `POST /admin/users` | administrator (`manage_users`) | never returns password hashes; POST audited |
| `GET /reference/admission-types`, `/admission-sources`, `/discharge-dispositions`, `/specialties`, `/age-groups` | any authenticated role | `[{id, label}]`; age groups in clinical order |

## Common list parameters
| Parameter | Type / limits | Default | Behaviour |
|---|---|---|---|
| `page` | int >= 1 | 1 | a page past the end returns `items: []` with the true `total` |
| `page_size` | int 1..100 | 25 | above 100 -> 422 |
| `sort_by` | whitelist per endpoint (unknown value -> 422) | see below | the primary key is always appended as a tiebreaker, in the same direction, so paging is stable |
| `sort_dir` | `asc` / `desc` | endpoint specific | |

## GET /encounters
| Parameter | Type / limits | Meaning |
|---|---|---|
| `sort_by` | `encounter_id, admission_date, time_in_hospital, num_medications, number_inpatient, age_order` | default `admission_date` desc |
| `date_from`, `date_to` | date | `admission_date >= date_from` and `<= date_to`, both inclusive; `date_from` after `date_to` -> 422 |
| `age_group` | one of the ten brackets, e.g. `[70-80)` | exact |
| `admission_type_id`, `admission_source_id`, `discharge_disposition_id` | int >= 1 | exact |
| `specialty` | text <= 80 | exact medical specialty name |
| `readmitted` | `NO`, `>30`, `<30` | exact |
| `min_los`, `max_los` | int 1..14, `min_los <= max_los` | inclusive length-of-stay range |
| `patient_nbr` | int > 0 | exact; **403 for the analyst role** |
| `q` | text <= 19 chars | **digits only**: exact `encounter_id` (also `patient_nbr` for administrator/clinical_ops, not for analysts). **Anything else**: ICD-9 prefix match on the encounter's diagnoses (`V57`, `E9`, `250.8`; case-insensitive; prefix only, never a suffix or substring). A number such as `250` is an id; write `250.` to search the ICD-9 prefix. Characters other than letters, digits and `.` -> 422 |

All filters combine with AND. `LIKE` wildcards typed by the user are escaped.

## GET /patients
`sort_by` in `patient_nbr` (default, asc), `created_at`; `q` = exact `patient_nbr`; `has_multiple_encounters` = true (more than one active encounter) or false. Each item has `encounter_count` (active encounters).

## Admin lists
| Endpoint | Filters | Sort |
|---|---|---|
| `/admin/audit-logs` | `user` (username), `action` (CREATE/UPDATE/DELETE/EXPORT), `entity_type`, `entity_id`, `date_from`, `date_to` (whole days, inclusive) | `created_at` (default desc), `id` |
| `/admin/pipeline-runs` | `status` (RUNNING/SUCCESS/FAILED/SKIPPED_DUPLICATE_FILE), `date_from`, `date_to` on `started_at` | `started_at` (default desc), `run_id` |
| `/admin/dq-issues` | `run_id`, `rule_name`, `severity` (error/warning/info) | `issue_id`, `rule_name` |
| `/admin/users` | none | `user_id`, `username` |

## Analytics
Shared filters on every endpoint: `date_from`, `date_to` (inclusive), `age_group`, `admission_type_id`. Response `{data, meta: {filters, denominator, dates_simulated: true, generated_at}}`.
Grouped rows: `id?, label, encounters, eligible_encounters, readmitted_30d, readmission_rate (0-1, null when eligible = 0), small_n (true if encounters < 11), avg_length_of_stay`.
* `/analytics/summary`: total encounters, unique patients, average LOS, average medications, eligible encounters, 30-day count, 30-day and any-readmission rates.
* `/analytics/admissions-trend?granularity=month|year`: periods without encounters are omitted.
* `/analytics/length-of-stay?group_by=age_group|admission_type|admission_source|specialty`: average, min, max and a 14-bucket histogram (index 0 = 1 day).
* `/analytics/readmissions?group_by=age_group|admission_type|admission_source|discharge_disposition|specialty|month`: age groups in `age_order`, months chronologically, others by volume.
* `/analytics/medications`: `top_drugs` (10), `insulin_status` (No/Steady/Up/Down), `a1c_result`. A drug row counts encounters in which the drug was prescribed, so drug rows can overlap; insulin and A1C groups partition the encounters.
* `/analytics/utilization`: prior inpatient visits 0, 1, 2, 3+.
Rates use eligible encounters as the denominator; volumes use all active encounters. Race and gender are never a grouping or a field.

## Reports
| Endpoint | Roles | Parameters |
|---|---|---|
| `GET /reports/export` | aggregated reports: all roles (`export_aggregated`); `encounters`: administrator and clinical_ops (`export_encounters`), analyst gets 403 | `report` = `admissions_trend`, `readmission_summary`, `length_of_stay_summary` or `encounters` (required); `format` = `csv` or `xlsx` (default `xlsx`); the shared analytics filters `date_from`, `date_to`, `age_group`, `admission_type_id` |
| `GET /reports/history` | administrator, clinical_ops | `report_type`, `date_from`, `date_to`, `page`, `page_size`, `sort_by` (`generated_at`, `report_id`), `sort_dir` |

Response: a file download. `Content-Disposition: attachment; filename="readmission_summary_20081231_153000.xlsx"` (no spaces), `X-Row-Count` = data rows. CSV = header row plus data only. Excel = `Summary`, one sheet per breakdown, `Metadata` (generated_at, filters, row count, the simulated-dates statement, the denominator and definitions). Encounter-level files have a fixed column list without race or gender and are capped at **50,000 rows** (413 `export_too_large` with the row count and limit; narrow with the filters). Every export writes a `report_runs` row; encounter-level exports also write an `EXPORT` audit row.

## Sample requests
```
curl -X POST http://127.0.0.1:8000/auth/login -d "username=admin&password=..."          # -> {"access_token": "...", "token_type": "bearer", "expires_in": 3600}
curl -H "Authorization: Bearer $T" "http://127.0.0.1:8000/encounters?age_group=%5B90-100%29&readmitted=%3C30&sort_by=time_in_hospital&page_size=5"
curl -H "Authorization: Bearer $T" "http://127.0.0.1:8000/analytics/readmissions?group_by=age_group"
curl -H "Authorization: Bearer $T" "http://127.0.0.1:8000/encounters?q=V57"
```
