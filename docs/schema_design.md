# Schema design (L2)

ERD: `docs/erd.png` (source `docs/erd.mmd`, rebuilt by `python scripts/make_diagrams.py`). Architecture sketch: `architecture/architecture_v0.png`.

## Keys and types
| Table | PK | FKs (ON DELETE) | Nullable / notes |
|---|---|---|---|
| patients | `patient_nbr` BIGINT | - | `race`, `gender` NULL; soft delete columns |
| encounters | `encounter_id` BIGINT | `patient_nbr` -> patients (RESTRICT); `admission_type_id`, `discharge_disposition_id`, `admission_source_id` -> ref_* (RESTRICT); `specialty_id`, `payer_id` -> ref_* (RESTRICT, nullable) | `admission_date`/`discharge_date` DATE (simulated); `age_order` TINYINT 1-10; `max_glu_serum` ENUM(None,Norm,>200,>300); `a1c_result` ENUM(None,Norm,>7,>8); `source_batch_id` NULL |
| encounter_outcomes | `encounter_id` | -> encounters (CASCADE) | `readmitted` ENUM(NO,>30,<30); three BOOL flags |
| encounter_diagnoses | (`encounter_id`, `position`) | -> encounters (CASCADE) | `icd9_code` VARCHAR(10) string |
| medications | `medication_id` | - | `drug_name` UNIQUE (23 names; 2 constant ones are never used) |
| encounter_medications | (`encounter_id`, `medication_id`) | -> encounters (CASCADE), -> medications (RESTRICT) | `dosage_status` ENUM(Steady,Up,Down) |
| ref_admission_type / ref_admission_source / ref_discharge_disposition | `id` INT (source ids) | - | disposition has `is_expired_or_hospice` |
| ref_medical_specialty, ref_payer | surrogate INT | - | `name` / `payer_code` UNIQUE |
| app_users, audit_logs, pipeline_runs, dq_issues, report_runs | see ERD | `audit_logs.user_id` -> app_users (SET NULL); `dq_issues.run_id` -> pipeline_runs (CASCADE) | `dq_issues.encounter_id` has no FK on purpose |

## Ten questions the system must answer, and the joins they need
| # | Question | Tables / joins |
|---|---|---|
| 1 | 30-day readmission rate by age group | encounters JOIN outcomes; WHERE `is_deleted=0` AND `is_readmission_eligible`; GROUP BY `age_order, age_group` |
| 2 | Average length of stay by admission type | encounters JOIN ref_admission_type; AVG(`time_in_hospital`) |
| 3 | Encounters per month (simulated) | encounters; GROUP BY year/month of `admission_date` |
| 4 | Readmission rate by discharge disposition (highest groups) | encounters JOIN outcomes JOIN ref_discharge_disposition; eligible denominator |
| 5 | Readmission rate by medical specialty | encounters JOIN outcomes JOIN ref_medical_specialty (NULL -> "Unknown") |
| 6 | Unique patients and encounters in a date range | encounters; COUNT(DISTINCT `patient_nbr`); `admission_date BETWEEN` |
| 7 | Medication usage: share of encounters with each drug, and insulin dosage change | encounter_medications JOIN medications / encounters |
| 8 | Search one patient's encounters (by `patient_nbr`) | patients JOIN encounters JOIN outcomes (race/gender only for permitted roles) |
| 9 | Readmission by admission source and prior inpatient visits | encounters JOIN ref_admission_source JOIN outcomes |
| 10 | Latest pipeline runs and data-quality issues for a batch | pipeline_runs JOIN dq_issues |

Hand-traced joins: **Q1** `SELECT e.age_order, e.age_group, SUM(o.readmitted_30d) / COUNT(*) FROM encounters e JOIN encounter_outcomes o ON o.encounter_id = e.encounter_id WHERE e.is_deleted = 0 AND o.is_readmission_eligible = 1 GROUP BY e.age_order, e.age_group ORDER BY e.age_order`. **Q5** `... FROM encounters e JOIN encounter_outcomes o USING (encounter_id) LEFT JOIN ref_medical_specialty s ON s.specialty_id = e.specialty_id WHERE ... GROUP BY COALESCE(s.name, 'Unknown')`.

## Design review (self-critique) and what was accepted
Ranked review of my first draft against the requirements. Decisions are also in `decision_log.md`.

| Rank | Issue | Resolution |
|---|---|---|
| HIGH | Readmission ambiguity: rate computed over all encounters, or `>30` read as 30-day | **Accepted.** `is_readmission_eligible` stored once in outcomes; `readmitted_30d` is only `<30`; contract states the denominator |
| HIGH | `race`/`gender` could leak via encounters or exports | **Accepted.** Only on `patients`; role filtering in API (L8-L9) |
| HIGH | `encounter_id` AUTO_INCREMENT would renumber on reload | **Accepted.** Source keys, no auto-increment |
| MEDIUM | Outcome flags are derivable from `readmitted`; storing them is redundant | **Rejected (kept stored).** One writer (ETL), one definition, indexable. Cost: three columns that could drift, covered by a consistency test |
| MEDIUM | Diagnoses as `diag_1..3` columns repeat a group (violates 1NF) | **Accepted.** Child table with `position` |
| MEDIUM | `dq_issues.encounter_id` as an FK would reject quarantined rows | **Accepted.** No FK on purpose; documented |
| MEDIUM | Age: patient attribute or encounter attribute? | Encounter: age changes between visits, so it stays on `encounters` |
| LOW | ENUM vs lookup for `readmitted`, `dosage_status`, lab results | ENUM (closed sets). Lookup tables for admission/discharge/specialty/payer (descriptions, extensible, FK-enforced) |
| LOW | Hospital table to answer "which hospitals" | **Rejected.** No hospital id exists; never invented |
| LOW | Over-normalising (separate tables for age group, lab results) | **Rejected** - stop at 3NF; extra joins add cost, not integrity |

## Planned indexes (not created until L12)
`encounters(patient_nbr)`, `encounters(admission_date)`, `encounters(is_deleted, admission_date)`, FK columns `admission_type_id`, `discharge_disposition_id`, `admission_source_id`, `specialty_id`; `encounter_outcomes(is_readmission_eligible, readmitted_30d)`; `encounter_medications(medication_id)`; `audit_logs(entity_type, entity_id)`, `audit_logs(created_at)`; `pipeline_runs(started_at)`; `dq_issues(run_id)`. Primary-key lookups by `encounter_id` and `patient_nbr` are already indexed.

## Why `medications` stores only prescribed drugs
A `No` cell means the drug was not prescribed. Storing it would write 2,137,086 rows (101,766 encounters x the 21 non-constant drugs), of which 94.4% are "No". Only 120,054 cells (5.6%) are Steady/Up/Down, so the long table is about 18x smaller and answers "who got drug X" with a simple join; a missing row means not prescribed.
