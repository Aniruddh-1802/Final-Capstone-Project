# Data profile - diabetic_data.csv

To: Hospital Operations team. All numbers are measured by `python src/etl/profile.py` (log: `logs/profile.log`).
The file is a de-identified research extract covering 1999-2008. It is **not** live data and has **no date columns**.

## Eight findings

1. **One row is one hospital encounter, not one patient.** The file has 101,766 rows and 50 columns. `encounter_id` is unique (101,766 distinct), but `patient_nbr` has only 71,518 distinct values. 16,773 patients appear more than once; the most frequent patient has 40 encounters. Never quote "patients" and "encounters" interchangeably.
2. **Missing data is written as `?`.** Measured after reading with `keep_default_na=False, na_values=['?','']`: `weight` 98,569 missing (96.86%), `medical_specialty` 49,949 (49.08%), `payer_code` 40,256 (39.56%), `race` 2,273 (2.23%), `diag_3` 1,423 (1.40%), `diag_2` 358 (0.35%), `diag_1` 21 (0.02%). No other column has missing values.
3. **The word `None` is a real value, and pandas defaults destroy it.** With a default `read_csv`, `max_glu_serum` shows 96,420 missing and `A1Cresult` 84,748 missing. With the contract read both have 0 missing and the literal `None` appears in exactly those rows ("test not performed"). Reporting the default-read figures would wrongly say most patients had no result recorded.
4. **Readmission mix.** `<30`: 11,357 (11.16%); `>30`: 35,545 (34.93%); `NO`: 54,864 (53.91%). The `<30` count is identical via `value_counts` and via a boolean mask.
5. **Expired/hospice discharges must leave the readmission denominator.** Discharge ids 11, 13, 14, 19, 20, 21 cover 2,423 encounters (2.38%): id 11 = 1,642; 13 = 399; 14 = 372; 19 = 8; 20 = 2; id 21 does not occur in this file. Eligible encounters = 99,343. The 30-day readmission rate is **11.39%** over eligible encounters versus 11.16% if the denominator is wrongly all encounters.
6. **Length of stay and counts.** `time_in_hospital` is 1-14 days (mean 4.40). `num_lab_procedures` 1-132 (mean 43.10); `num_procedures` 0-6; `num_medications` 1-81 (mean 16.02); `number_outpatient` 0-42; `number_emergency` 0-76; `number_inpatient` 0-21; `number_diagnoses` 1-16 (mean 7.42). The extreme `number_emergency` / `number_outpatient` values are plausible but rare; they are range-checked in L5, not silently dropped.
7. **Code columns need care.** `gender` has 3 rows of `Unknown/Invalid` (54,708 Female, 47,055 Male). `age` is ten brackets from `[0-10)` to `[90-100)` (these happen to sort correctly as text in this file, but the contract still requires an explicit `age_order` 1-10 so ordering never depends on string comparison). ICD-9 diagnosis codes are strings: 7,263 start with `V`, 1,976 with `E`, 20,848 contain a decimal point across diag_1-3. `admission_type_id`, `discharge_disposition_id` and `admission_source_id` values are all present in `IDs_mapping.csv`, but several map to "NULL / Not Available / Not Mapped / Unknown" descriptions (e.g. discharge 18 = 3,691 rows, admission source 17 = 6,781 rows, admission type 6 = 5,291 rows); these stay as they are and are reported as unknown categories.
8. **Medication columns are mostly "No".** There are 23 drug columns with values `No`, `Steady`, `Up`, `Down`. `examide` and `citoglipton` are constant (all `No`) and are dropped. Ten more columns are >= 99.9% `No`. `insulin` (46.56% "No") and `metformin` (80.36% "No") are the most used. No fully duplicated rows exist when `encounter_id` is ignored (0).

## Column decisions

| Column(s) | Decision | Reason |
|---|---|---|
| `encounter_id`, `patient_nbr` | keep as BIGINT, source keys | Source identity; never auto-generated |
| `weight` | **drop** | 96.86% missing |
| `examide`, `citoglipton` | **drop** | Constant value in every row |
| `race`, `gender` | keep, patients table only | Sensitive; one place; `Unknown/Invalid` gender kept as a value, not guessed |
| `age` | transform | Keep `age_group` text + derive `age_order` 1-10 |
| `payer_code`, `medical_specialty` | keep, NULL when `?` | Heavily missing; moved to lookup tables in the loader |
| `admission_type_id`, `admission_source_id`, `discharge_disposition_id` | keep as FK ids | Descriptions come from `IDs_mapping.csv` lookups |
| `diag_1`..`diag_3` | transform | Rows in `encounter_diagnoses` (position 1-3), always strings |
| `max_glu_serum`, `A1Cresult` | keep | `None` is a legitimate value (not tested) |
| 21 remaining drug columns | transform | Long format; only `Steady`/`Up`/`Down` stored |
| `change`, `diabetesMed` | rename `med_changed`, `diabetes_med` | snake_case; `Ch`/`No` and `Yes`/`No` |
| `readmitted` | keep + derive | `readmitted_30d`, `any_readmission`, `is_readmission_eligible` |
| `admission_date`, `discharge_date` | **create (simulated)** | Dataset has no dates; labelled as simulated everywhere |

## IDs_mapping.csv layout
Three tables stacked in one file: `admission_type_id` (8 rows), `discharge_disposition_id` (30 rows, not in id order: 30 precedes 27), `admission_source_id` (25 rows). They are separated by a row containing only a comma (`,`), not an empty line. Each block starts with its own header row. Some descriptions contain commas and are quoted; several admission-source descriptions have leading spaces that must be stripped. The parser is `etl.extract.read_id_mappings` (L3).
