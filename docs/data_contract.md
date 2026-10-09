# Data contract

Single source of truth for names, grain and rules. If code, a lab or another document disagrees with this file, this file wins.
Source: UCI *Diabetes 130-US Hospitals for Years 1999-2008* (`diabetic_data.csv`, `IDs_mapping.csv`). Educational use only.

## 1. Files
| File | Role | Location |
|---|---|---|
| `diabetic_data.csv` | One row per encounter, 50 columns, 101,766 rows (measured) | `data/raw/` - git-ignored, never edited |
| `IDs_mapping.csv` | Three stacked lookup tables (separator row is `,`) | `data/reference/` |
| `encounters_batch_*.csv` | Prepared batches with simulated dates (L4) | `data/incoming/`, `data/held_back/` |

## 2. Grain and identity
- One raw row = one hospital **encounter**. `encounter_id` is unique. `patient_nbr` repeats (71,518 patients across 101,766 encounters).
- `encounter_id` and `patient_nbr` come from the source, are stored as BIGINT and are **never auto-generated**.

## 3. Missing values
- `?` is missing. Read with `keep_default_na=False, na_values=['?','']`.
- `None` in `max_glu_serum` and `A1Cresult` is a **value** (test not performed), not missing.
- `weight` (96.86% missing) is not loaded. `examide` and `citoglipton` (constant) are not loaded.
- `payer_code`, `medical_specialty`, `race`, `diag_2`, `diag_3` stay NULL when missing. `diag_1` missing (21 rows) is a data-quality finding (L5).

## 4. Field rules
| Field | Rule |
|---|---|
| `age_group` / `age_order` | Source bracket such as `[70-80)`; `age_order` = 1..10 from `[0-10)`..`[90-100)`. Sort by `age_order`. |
| `diag_1..3` | ICD-9 **strings** (V/E codes, decimal points). Stored in `encounter_diagnoses(position 1-3)`; `diag_1` is primary. Never cast to number. |
| Medications | 23 drug columns -> `snake_case`. Only `Steady`/`Up`/`Down` are stored in `encounter_medications`; `No` means not prescribed and is not stored. |
| `change`, `diabetesMed` | Stored as `med_changed` (`Ch` = TRUE) and `diabetes_med` (`Yes` = TRUE). |
| `gender` | `Female`, `Male`; the source value `Unknown/Invalid` (3 rows) is stored as `Unknown` (DQ12 flags it). Not imputed. |
| Soft delete | `is_deleted` / `deleted_at` on `patients` and `encounters`. **Every** list, analytics and export query excludes deleted rows. |

## 5. Outcome and readmission definition
| Field | Definition |
|---|---|
| `readmitted` | Source label: `NO`, `>30`, `<30` |
| `readmitted_30d` | Derived: `readmitted == '<30'` |
| `any_readmission` | Derived: `readmitted` in (`<30`, `>30`) |
| `is_readmission_eligible` | FALSE when `discharge_disposition_id` in (11, 13, 14, 19, 20, 21) - expired or hospice discharges |

**Denominator rule (plain words):** the 30-day readmission rate is the number of non-deleted encounters with `readmitted_30d` divided by the number of non-deleted **eligible** encounters. Patients who died or went to hospice could not be readmitted, so they are removed from the denominator of *every* readmission rate. They still count as encounters and in length of stay. Measured on the full file: 11,357 / 99,343 = **11.39%** (not 11.16%, which wrongly divides by all 101,766).

The rate is per **encounter**, not per patient. The source label describes whether the next admission followed, so a patient's last encounter in the extract is labelled by the source, not recomputed by us.

## 6. Simulated fields (training constructs)
The dataset has no dates. To support trends, date-range queries and incremental loading we simulate them.
| Field | Rule |
|---|---|
| `admission_date` | Seeded (`numpy.random.default_rng(seed=42)`) random dates 1999-01-01..2008-12-31, drawn from a day-level distribution with about +4% yearly growth and a +/-15% winter peak (mid-January), **sorted ascending and assigned in `encounter_id` order**, generated once by `scripts/prepare_batches.py` so batch files arrive with dates. Re-running produces byte-identical files. Stored as `DATE`. |
| `discharge_date` | `admission_date + time_in_hospital` days. The ETL validates the two agree. |

**Why acceptable:** the project teaches pipelines, SQL, APIs and dashboards; it needs a time axis for those mechanics. **What we must never claim:** that any monthly or yearly pattern, seasonality or growth is a clinical or epidemiological finding. Every UI, API response (`meta.dates_simulated = true`), report and document that shows dates says they are simulated.

## 7. Privacy and ethics
- `race` and `gender` live only on `patients`. Visible to administrator and clinical_ops; hidden from analyst. Never used as a dashboard breakdown, never in exports.
- Analyst responses omit `patient_nbr` (data minimisation).
- Analytics groups with fewer than 11 encounters carry `small_n = true`.
- Say "associated with", never "caused by". Observational, de-identified research data.
- Passwords, tokens and sensitive demographics never appear in logs or error messages.

## 8. Permission matrix (single constant in `src/app/permissions.py`; a test compares this table with the code)
| Key | Capability | administrator | clinical_ops | analyst |
|---|---|---|---|---|
| `dashboards` | Dashboards and analytics endpoints | Yes | Yes | Yes |
| `export_aggregated` | Export aggregated reports | Yes | Yes | Yes |
| `list_encounters` | List and search encounters | Yes | Yes | Yes, without `patient_nbr` |
| `export_encounters` | Export encounter-level data | Yes | Yes | No |
| `view_patients` | View patient records (race, gender) | Yes | Yes | No (403) |
| `write_records` | Create and update patients and encounters | Yes | Yes | No |
| `delete_records` | Soft-delete patients and encounters | Yes | No | No |
| `view_pipeline` | View pipeline runs and data-quality issues | Yes | Yes (read) | No |
| `view_audit` | View audit logs | Yes | No | No |
| `manage_users` | Manage users | Yes | No | No |

Authentication: `POST /auth/login` (OAuth2 password form) returns a bearer JWT (HS256) holding only `sub` (user id), `role`, `iat` and `exp`; default lifetime `JWT_EXPIRE_MINUTES` = 60. No token or an invalid/expired one gives 401; a valid token without the capability gives 403. Roles are always read from the database, never trusted from the token. The service refuses to start if `JWT_SECRET` is missing, shorter than 32 characters or a placeholder.
All create, update, delete and encounter-level export actions are audited.

## 8a. KPI definitions (SQL in db/queries/kpi_queries.sql, all reading the views)
| KPI | Definition | Denominator |
|---|---|---|
| Total encounters | rows of _active_encounters (non-deleted encounters of non-deleted patients) | - |
| Unique patients | COUNT(DISTINCT patient_nbr) over active encounters | - |
| Average length of stay | AVG(time_in_hospital) over active encounters (includes expired/hospice discharges) | all active encounters |
| 30-day readmission rate | encounters with eadmitted_30d and is_readmission_eligible / eligible encounters | **eligible encounters** |
| Any-readmission rate | <30 or >30 among eligible encounters / eligible encounters | eligible encounters |
| Grouped rates (age, admission type/source, discharge disposition, specialty, A1C, insulin, prior inpatient, drug) | same rate within the group | eligible encounters in the group |
| Monthly / yearly rate and 3-month moving average | same rate per admission month/year (SIMULATED dates); moving average = mean of the current and two previous monthly rates | eligible encounters in the period |
| Frequent patients | patients with 3 or more active encounters (counts only, no identifiers) | - |

Verified against pandas on the raw CSV by scripts/verify_kpis.py (59 of 59 checks passed on the loaded data). On the loaded data the 30-day rate is 0.114258 over eligible encounters; dividing by all encounters would give 0.111548, which understates it by 0.00271.

## 8b. Data-quality rules (implemented in `src/etl/quality.py`; thresholds below match the code)
File policy: if the rejected share of a file exceeds `MAX_REJECT_RATIO` (default 0.20) the whole file is FAILED and nothing loads. Otherwise good rows load and bad rows go to `data/rejected/<batch>_rejected.csv` (original columns + `rule_name` + `reason`) and to `dq_issues` (at most 500 example rows per rule; true counts are in the run summary). A row failing several rules is reported once per rule and removed once.

| Rule | Check | Action |
|---|---|---|
| DQ01 | `encounter_id` or `patient_nbr` missing, non-numeric, non-integer or <= 0 | Reject |
| DQ02 | Duplicate `encounter_id` inside the file | Keep first, reject the rest |
| DQ03 | `admission_type_id`, `admission_source_id` or `discharge_disposition_id` not in the reference tables (or non-numeric) | Reject |
| DQ04 | `readmitted` not NO/>30/<30; `age` not one of the 10 brackets; `gender` not Male/Female/Unknown/Unknown-Invalid; any drug column not No/Steady/Up/Down; `max_glu_serum` not None/Norm/>200/>300; `A1Cresult` not None/Norm/>7/>8; `change` not Ch/No; `diabetesMed` not Yes/No (the last four mirror the database ENUMs) | Reject |
| DQ05 | `time_in_hospital` 1-14; counts >= 0 and <= caps: lab procedures 250, procedures 20, medications 150, outpatient 100, emergency 150, inpatient 50, diagnoses 30 (caps are about 2x the maximum in the source: 132, 6, 81, 42, 76, 21, 16); missing or non-numeric also fails | Reject |
| DQ06 | ICD-9 format `^(\d{1,3}(\.\d{1,2})?\|V\d{1,2}(\.\d{1,2})?\|E\d{3}(\.\d{1,2})?)$`. Short codes are **valid**: the source lost leading zeros (e.g. `38` for 038); 5,732 of 303,496 real codes would fail a strict 3-digit rule. Codes are never zero-padded or cast to numbers | Set NULL, flag as corrected |
| DQ07 | `admission_date` / `discharge_date` missing or not ISO `YYYY-MM-DD` | Reject |
| DQ08 | `admission_date` outside 1999-01-01..2008-12-31 or in the future; `discharge_date` before 1999-01-01, after 2009-01-14 (window end + 14 days, the longest stay) or in the future | Reject |
| DQ09 | `discharge_date` earlier than `admission_date` | Reject |
| DQ10 | `(discharge_date - admission_date)` in days differs from `time_in_hospital`. Evaluated only where the dates and stay length are individually valid, so one fault is reported by one rule | Reject |
| DQ11 | Missing values per column | Metric only (`dq_summary_json`, `dq_issues` action `metric`) |
| DQ12 | `gender` = `Unknown/Invalid` | Keep as `Unknown`, flag |
| DQ13 | Same `patient_nbr` with conflicting `race` or `gender` across rows of the file | Keep first non-null (lowest `encounter_id`), flag |

Measured on genuine data: the initial batch (81,412 rows), batch 001 and held-back batch 003 all reject **0 rows**; DQ12/DQ13 only flag (initial batch: 2 and 273 rows). Several rules (DQ02, DQ03, DQ05, DQ09) legitimately return zero on genuine data; they earn their place on the faulty batch (`scripts/make_faulty_batch.py`), which injects 5 duplicate ids, 5 unknown dispositions, 5 negative stays, 5 discharge-before-admission dates, 5 malformed ICD codes and 3 missing `patient_nbr` and is rejected row-for-row (23 rows rejected, 5 corrected).

## 9. Known limitations
1. **Dates are simulated.** Trends are illustrative only.
2. **No hospital identifier.** "Which hospitals have higher readmission?" cannot be answered; we compare admission type, admission source, discharge disposition and medical specialty instead. No hospital table is invented.
3. **Heavy missingness** in `medical_specialty` (49%) and `payer_code` (40%); category comparisons by these fields describe only the recorded subset.
4. **Repeated patients.** Encounters of one patient are not independent; rates are per encounter.
5. **Dated data (1999-2008).** Not a description of current practice; not real-time.
6. **Coded "unknown" categories** (e.g. discharge 18, admission source 17, admission type 6) are retained as unknown, not imputed.

