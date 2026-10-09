# Dataset Details

| | |
|---|---|
| **Name** | Diabetes 130-US Hospitals for Years 1999-2008 |
| **Source** | UCI Machine Learning Repository (donated 2014-05-02) |
| **Link** | https://archive.ics.uci.edu/dataset/296/diabetes+130-us+hospitals+for+years+1999-2008 |
| **DOI** | 10.24432/C5230J |
| **Licence** | Creative Commons Attribution 4.0 International (CC BY 4.0), as stated on the UCI page |
| **Citation** | Strack, B., DeShazo, J., Gennings, C., Olmo, J., Ventura, S., Cios, K., & Clore, J. (2014). Impact of HbA1c Measurement on Hospital Readmission Rates: Analysis of 70,000 Clinical Database Patient Records. *BioMed Research International*, 2014. |
| **Format** | Two CSV files: `diabetic_data.csv` (101,766 rows, 50 columns) and `IDs_mapping.csv` (three lookup tables stacked in one file) |
| **Purpose in this project** | Teaching data for an end-to-end healthcare data system: ETL, quality control, a relational database, a secured REST API, KPI analytics and a dashboard. **Educational use only.** |

## 1. What one row means
One row is one hospital **encounter** (an inpatient stay) of a diabetic patient at one of 130 US hospitals, 1999-2008. `encounter_id` is unique (101,766 distinct values). `patient_nbr` repeats: there are **71,518 distinct patients**, 16,773 of whom appear more than once (the most frequent has 40 encounters). Patients and encounters are therefore never used interchangeably in this project.

## 2. Key fields
| Field | Meaning | How it is used |
|---|---|---|
| `encounter_id`, `patient_nbr` | Source keys (BIGINT, never generated) | Primary keys of `encounters` and `patients` |
| `age` | Ten brackets `[0-10)` ... `[90-100)` | Stored as `age_group` plus `age_order` 1-10; always sorted by `age_order` |
| `race`, `gender` | Demographics (sensitive) | Stored only on `patients`; hidden from the analyst role; never a dashboard breakdown, never exported |
| `admission_type_id`, `admission_source_id`, `discharge_disposition_id` | Coded categories | Foreign keys to lookup tables loaded from `IDs_mapping.csv` (8, 25 and 30 rows) |
| `medical_specialty`, `payer_code` | Admitting specialty, payer | Lookup tables; NULL when missing |
| `time_in_hospital` | Length of stay in days (1-14) | Length-of-stay KPIs |
| `num_lab_procedures`, `num_procedures`, `num_medications`, `number_outpatient`, `number_emergency`, `number_inpatient`, `number_diagnoses` | Counts of services and prior visits | Stored on `encounters`; prior inpatient visits drive the utilisation analysis |
| `diag_1`, `diag_2`, `diag_3` | ICD-9 diagnosis codes (strings, include `V` and `E` codes) | Rows in `encounter_diagnoses` (position 1-3) |
| `max_glu_serum`, `A1Cresult` | Lab results; the text `None` means "test not performed" | Stored as ENUMs; `None` is a real value |
| 23 drug columns (`metformin` ... `metformin-pioglitazone`) | `No`, `Steady`, `Up`, `Down` | Long table `encounter_medications` holding only `Steady`/`Up`/`Down` |
| `change`, `diabetesMed` | Medication change, diabetes medication prescribed | `med_changed`, `diabetes_med` booleans |
| `readmitted` | `NO`, `>30`, `<30` | The outcome; see section 4 |

## 3. Preprocessing performed (every rule)
### 3.1 Reading
- `?` is read as missing (`keep_default_na=False, na_values=['?','']`). The literal text `None` in `max_glu_serum` and `A1Cresult` is **kept**: with pandas defaults it would be turned into missing (96,420 and 84,748 rows), wrongly suggesting that most patients have no lab result.
- ICD-9 columns are read as text so that `V` and `E` codes and decimal points survive.

### 3.2 Columns removed
| Column | Reason |
|---|---|
| `weight` | 96.86% missing |
| `examide`, `citoglipton` | constant value (`No`) in every row |

### 3.3 Transformations
- Column names to `snake_case`; `change` to `med_changed` (`Ch` = true), `diabetesMed` to `diabetes_med` (`Yes` = true).
- `age` to `age_group` plus `age_order` (1-10).
- `diag_1..3` to three rows per encounter at most, in `encounter_diagnoses`.
- The 21 informative drug columns to long format; rows with `No` are **not stored** (120,054 prescribed cells instead of 2,137,086 rows, 94.4% of which would be "No").
- `gender` value `Unknown/Invalid` (3 rows) stored as `Unknown` and flagged (DQ12); never imputed.
- Race and gender are taken per patient: the first non-null value by lowest `encounter_id`; a conflict inside a file is flagged (DQ13).

### 3.4 Data-quality rules (code: `src/etl/quality.py`; full table: `docs/data_contract.md` section 8b)
| Rule | Check | Action |
|---|---|---|
| DQ01 | key columns present, integer, positive | reject |
| DQ02 | duplicate `encounter_id` in the file | keep first, reject rest |
| DQ03 | admission type, source or disposition id not in the reference tables | reject |
| DQ04 | value outside the allowed set (`readmitted`, `age`, `gender`, drug status, lab results, `change`, `diabetesMed`) | reject |
| DQ05 | numeric ranges (stay 1-14; counts non-negative and below caps) | reject |
| DQ06 | ICD-9 format (short numeric codes are valid: the source dropped leading zeros) | set code to NULL and flag |
| DQ07 | dates missing or not ISO `YYYY-MM-DD` | reject |
| DQ08 | dates outside 1999-01-01..2008-12-31 (discharge up to 14 days later) or in the future | reject |
| DQ09 | discharge before admission | reject |
| DQ10 | date difference differs from `time_in_hospital` | reject |
| DQ11 | missing values per column | metric only |
| DQ12 | gender `Unknown/Invalid` | keep as `Unknown`, flag |
| DQ13 | conflicting race or gender for one patient in a file | keep first non-null, flag |

A file in which more than 20% of rows are rejected fails as a whole and loads nothing; otherwise good rows load and bad rows are written to `data/rejected/` with the rule and reason. On the genuine data every batch is rejected **0 rows**; the rules are demonstrated on a deliberately faulty batch (23 rows rejected, 5 corrected).

### 3.5 Derived fields
| Field | Definition |
|---|---|
| `readmitted_30d` | `readmitted == '<30'` |
| `any_readmission` | `readmitted` is `<30` or `>30` |
| `is_readmission_eligible` | false when `discharge_disposition_id` is 11, 13, 14, 19, 20 or 21 (expired or hospice) |
| `age_order` | position of the age bracket, 1-10 |

## 4. The readmission rate
The 30-day readmission rate is `readmitted_30d` among eligible encounters divided by the number of **eligible** encounters. Patients who died or entered hospice could not be readmitted, so they leave the denominator (2,423 encounters). On the full data this is 11,314 / 99,343 = **0.113888** (11.39%). Dividing by all 101,766 encounters would give 0.111177, which understates the rate without raising any error. The rate is per encounter, not per patient.

## 5. SIMULATED fields (not in the source)
The source has **no dates**. To support trends, date-range queries and incremental loading, two fields are created:

| Field | Rule |
|---|---|
| `admission_date` | **Simulated.** Seeded random dates (`numpy.random.default_rng(seed=42)`) between 1999-01-01 and 2008-12-31 with mild growth and winter seasonality, sorted and assigned in `encounter_id` order. Re-running produces identical files. |
| `discharge_date` | **Simulated.** `admission_date + time_in_hospital` days. |

Every dashboard, API response (`meta.dates_simulated = true`), report and document that shows a date says so. Monthly or yearly patterns are illustrative and must never be read as clinical or epidemiological findings.

## 6. Other limitations of the data
- **No hospital identifier:** hospital-level comparisons are impossible; admission type, admission source, discharge disposition and specialty are compared instead.
- **Missingness:** `medical_specialty` 49.08% and `payer_code` 39.56% missing; category comparisons describe only the recorded subset.
- **Repeated patients:** encounters of one patient are not independent.
- **Dated and observational:** 1999-2008 data; findings are associations, not causes, and do not describe current practice.
- **Coded unknown categories** (for example discharge disposition 18, admission source 17) are kept as unknown, not imputed.

## 7. Privacy note
The extract is de-identified research data released for public use. The system still treats it as sensitive: `race` and `gender` exist only on the `patients` table, are visible only to administrators and clinical operations staff, never appear in exports, analytics, logs or error messages, and analytics groups with fewer than 11 encounters are flagged `small_n`. Analysts see encounters without `patient_nbr`. Raw data files are not committed to the repository. The system is for education only and must not be used for clinical decisions.
