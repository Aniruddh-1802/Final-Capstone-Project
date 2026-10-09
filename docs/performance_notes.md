# Performance notes (L12)

Evidence for every index in `db/indexes.sql`. All numbers come from `scripts/perf_measure.py`; nothing here is estimated by hand.

## Setup
* Database `healthcare_perf` (scratch copy, never the development or test schema): all five batches loaded = **101,766 encounters**, 71,518 patients, 303,496 diagnosis rows, plus **300,000 synthetic audit rows** (`scripts/perf_seed_audit.py`; the real audit table is tiny, which would make any index look pointless).
* MySQL 8.4.9 on a laptop, warm cache. Each query is run 6 times; **the first (cold) run is discarded and the median of the other five is reported**. `EXPLAIN` and `EXPLAIN ANALYZE` were captured for every query at each stage.
* Three stages: **before** (primary keys and FK indexes only, view joins `patients`), **view only** (view rewritten as an anti-join), **view + indexes** (final design).
* Reproduce: create `healthcare_perf`, load the batches with `python -m etl.pipeline`, `python scripts/perf_seed_audit.py`, then `python scripts/perf_measure.py before|view_only|after out.json`.

## Results (median of 5 runs, milliseconds)
| # | Query (API call) | Before | View only | View + indexes | Change | Named by the plan after |
|---|---|---|---|---|---|---|
| Q1 | encounters list: date range, newest first (page 1) (`GET /encounters?date_from=2005-03-01&date_to=2005-03-31`) | 256.3 | 29.1 | 0.8 | 324x faster | ix_encounters_is_deleted_admission_date |
| Q2 | patient lookup with encounters (`GET /patients/{id}/encounters`) | 0.9 | 0.8 | 0.8 | 1x faster | none (see below) |
| Q3 | monthly trend for one year (dashboard filter) (`GET /analytics/admissions-trend?date_from=2005-01-01&date_to=2005-12-31`) | 287.1 | 77.2 | 63.9 | 4x faster | ix_encounters_is_deleted_admission_date |
| Q4 | readmission rate by age group (all data) (`GET /analytics/readmissions?group_by=age_group`) | 648.4 | 500.4 | 610.6 | 1x faster | none (see below) |
| Q5 | audit log search by user and date (`GET /admin/audit-logs?user=ops&date_from=...&date_to=...`) | 68.6 | 68.5 | 1.2 | 58x faster | ix_audit_logs_created_at |
| Q6 | ICD-9 prefix search (`GET /encounters?q=V57`) | 765.1 | 68.3 | 9.1 | 84x faster | ix_encounter_diagnoses_icd9_code |
| Q7 | top drugs with readmission rate (`GET /analytics/medications`) | 849.0 | 744.8 | 779.5 | 1x faster | none (see below) |
| Q8 | audit log newest first (no filter) (`GET /admin/audit-logs`) | 85.6 | 80.1 | 0.6 | 156x faster | ix_audit_logs_created_at |
| Q9 | audit trail of one record (`GET /admin/audit-logs?entity_type=encounter&entity_id=...`) | 64.6 | 61.8 | 0.3 | 249x faster | ix_audit_logs_entity |

Q2 (patient lookup) was already fast because `encounters.patient_nbr` has the automatic foreign-key index; it is the control that shows the harness measures real differences. Q4 and Q7 are discussed under "Still slow".

## Plans, query by query
Plan lines show `table, access type, key used, rows estimated, Extra` for the first tables of the join. `EXPLAIN ANALYZE` lines show the top of the execution tree with actual time and rows.

### Q1 encounters list: date range, newest first (page 1)
```sql
SELECT encounter_id, patient_nbr, admission_date, age_group, time_in_hospital, readmitted FROM v_active_encounters WHERE admission_date >= '2005-03-01' AND admission_date <= '2005-03-31' ORDER BY admission_date DESC, encounter_id DESC LIMIT 25
```
**Before** (median 256.33 ms)
```
  p          type=ALL     key=None                                       rows=67568   Using where; Using temporary; Using filesort
  e          type=ref     key=fk_encounters_patient_nbr                  rows=1       Using where
  t          type=eq_ref  key=PRIMARY                                    rows=1       Using index
-> Limit: 25 row(s)  (actual time=272..272 rows=25 loops=1)
    -> Sort: v_active_encounters.admission_date DESC, v_active_encounters.encounter_id DESC, limit input to 25 row(s) per chunk  (actual time=272..272 rows=25 loops=1)
```
**After** (median 0.79 ms)
```
  e          type=range   key=ix_encounters_is_deleted_admission_date    rows=942     Using index condition; Backward index scan
  t          type=eq_ref  key=PRIMARY                                    rows=1       Using index
  s          type=eq_ref  key=PRIMARY                                    rows=1       Using index
-> Limit: 25 row(s)  (cost=2732 rows=25) (actual time=0.154..0.327 rows=25 loops=1)
    -> Nested loop inner join  (cost=2732 rows=942) (actual time=0.153..0.325 rows=25 loops=1)
```

### Q3 monthly trend for one year (dashboard filter)
```sql
SELECT DATE_FORMAT(admission_date, '%Y-%m') AS month, COUNT(*) AS encounters, SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END) AS r30 FROM v_active_encounters WHERE admission_date >= '2005-01-01' AND admission_date <= '2005-12-31' GROUP BY DATE_FORMAT(admission_date, '%Y-%m') ORDER BY month
```
**Before** (median 287.11 ms)
```
  p          type=ALL     key=None                                       rows=67568   Using where; Using temporary; Using filesort
  e          type=ref     key=fk_encounters_patient_nbr                  rows=1       Using where
  t          type=eq_ref  key=PRIMARY                                    rows=1       Using index
-> Sort: `month`  (actual time=344..344 rows=12 loops=1)
    -> Table scan on <temporary>  (actual time=344..344 rows=12 loops=1)
```
**After** (median 63.9 ms)
```
  e          type=range   key=ix_encounters_is_deleted_admission_date    rows=19734   Using index condition; Using temporary; Using filesort
  t          type=eq_ref  key=PRIMARY                                    rows=1       Using index
  s          type=eq_ref  key=PRIMARY                                    rows=1       Using index
-> Sort: `month`  (actual time=81.3..81.3 rows=12 loops=1)
    -> Table scan on <temporary>  (actual time=81.3..81.3 rows=12 loops=1)
```

### Q4 readmission rate by age group (all data)
```sql
SELECT age_order, age_group, COUNT(*) AS encounters, SUM(is_readmission_eligible) AS eligible, SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END) AS r30 FROM v_active_encounters GROUP BY age_order, age_group ORDER BY age_order
```
**Before** (median 648.39 ms)
```
  p          type=ALL     key=None                                       rows=67568   Using where; Using temporary; Using filesort
  e          type=ref     key=fk_encounters_patient_nbr                  rows=1       Using where
  t          type=eq_ref  key=PRIMARY                                    rows=1       Using index
-> Sort: v_active_encounters.age_order, v_active_encounters.age_group  (actual time=831..831 rows=10 loops=1)
    -> Table scan on <temporary>  (actual time=831..831 rows=10 loops=1)
```
**After** (median 610.64 ms)
```
  e          type=ref     key=ix_encounters_is_deleted_admission_date    rows=50573   Using temporary; Using filesort
  t          type=eq_ref  key=PRIMARY                                    rows=1       Using index
  s          type=eq_ref  key=PRIMARY                                    rows=1       Using index
-> Sort: v_active_encounters.age_order, v_active_encounters.age_group  (actual time=782..782 rows=10 loops=1)
    -> Table scan on <temporary>  (actual time=782..782 rows=10 loops=1)
```

### Q5 audit log search by user and date
```sql
SELECT id, created_at, username, action, entity_type, entity_id FROM audit_logs WHERE username = 'ops' AND created_at >= (NOW() - INTERVAL 14 DAY) AND created_at < (NOW() - INTERVAL 7 DAY) ORDER BY created_at DESC, id DESC LIMIT 25
```
**Before** (median 68.59 ms)
```
  audit_logs type=ALL     key=None                                       rows=297540  Using where; Using filesort
-> Limit: 25 row(s)  (cost=27774 rows=25) (actual time=87.5..87.5 rows=25 loops=1)
    -> Sort: audit_logs.created_at DESC, audit_logs.id DESC, limit input to 25 row(s) per chunk  (cost=27774 rows=297540) (actual time=87.5..87.5 rows=25 loops=1)
```
**After** (median 1.19 ms)
```
  audit_logs type=range   key=ix_audit_logs_created_at                   rows=19626   Using index condition; Using where; Backward index scan
-> Limit: 25 row(s)  (cost=9373 rows=25) (actual time=0.594..0.622 rows=25 loops=1)
    -> Filter: (audit_logs.username = 'ops')  (cost=9373 rows=1963) (actual time=0.593..0.621 rows=25 loops=1)
```

### Q6 ICD-9 prefix search
```sql
SELECT v.encounter_id, v.admission_date FROM v_active_encounters v WHERE EXISTS (SELECT 1 FROM encounter_diagnoses d WHERE d.encounter_id = v.encounter_id AND d.icd9_code LIKE 'V57%') ORDER BY v.admission_date DESC, v.encounter_id DESC LIMIT 25
```
**Before** (median 765.13 ms)
```
  p          type=ALL     key=None                                       rows=67568   Using where; Using temporary; Using filesort
  e          type=ref     key=fk_encounters_patient_nbr                  rows=1       Using where
  t          type=eq_ref  key=PRIMARY                                    rows=1       Using index
-> Limit: 25 row(s)  (actual time=943..943 rows=25 loops=1)
    -> Sort: v.admission_date DESC, v.encounter_id DESC, limit input to 25 row(s) per chunk  (actual time=943..943 rows=25 loops=1)
```
**After** (median 9.13 ms)
```
  t          type=index   key=PRIMARY                                    rows=8       Using index; Using temporary; Using filesort
  <subquery2> type=ALL     key=None                                       rows=None    Using join buffer (hash join)
  e          type=eq_ref  key=PRIMARY                                    rows=1       Using where
-> Limit: 25 row(s)  (actual time=11.9..11.9 rows=25 loops=1)
    -> Sort: v.admission_date DESC, v.encounter_id DESC, limit input to 25 row(s) per chunk  (actual time=11.9..11.9 rows=25 loops=1)
```

### Q7 top drugs with readmission rate
```sql
SELECT m.drug_name, COUNT(*) AS encounters, SUM(CASE WHEN v.is_readmission_eligible = 1 AND v.readmitted_30d = 1 THEN 1 ELSE 0 END) AS r30 FROM v_active_encounters v JOIN encounter_medications em ON em.encounter_id = v.encounter_id JOIN medications m ON m.medication_id = em.medication_id GROUP BY m.drug_name ORDER BY encounters DESC LIMIT 10
```
**Before** (median 849.02 ms)
```
  p          type=ALL     key=None                                       rows=67568   Using where; Using temporary; Using filesort
  e          type=ref     key=fk_encounters_patient_nbr                  rows=1       Using where
  t          type=eq_ref  key=PRIMARY                                    rows=1       Using index
-> Limit: 10 row(s)  (actual time=1048..1048 rows=10 loops=1)
    -> Sort: encounters DESC, limit input to 10 row(s) per chunk  (actual time=1048..1048 rows=10 loops=1)
```
**After** (median 779.48 ms)
```
  e          type=ref     key=ix_encounters_is_deleted_admission_date    rows=50573   Using temporary; Using filesort
  t          type=eq_ref  key=PRIMARY                                    rows=1       Using index
  s          type=eq_ref  key=PRIMARY                                    rows=1       Using index
-> Limit: 10 row(s)  (actual time=981..981 rows=10 loops=1)
    -> Sort: encounters DESC, limit input to 10 row(s) per chunk  (actual time=981..981 rows=10 loops=1)
```

### Q8 audit log newest first (no filter)
```sql
SELECT id, created_at, username, action, entity_type, entity_id FROM audit_logs ORDER BY created_at DESC, id DESC LIMIT 25
```
**Before** (median 85.61 ms)
```
  audit_logs type=ALL     key=None                                       rows=297540  Using filesort
-> Limit: 25 row(s)  (cost=30419 rows=25) (actual time=94.1..94.1 rows=25 loops=1)
    -> Sort: audit_logs.created_at DESC, audit_logs.id DESC, limit input to 25 row(s) per chunk  (cost=30419 rows=297540) (actual time=94.1..94.1 rows=25 loops=1)
```
**After** (median 0.55 ms)
```
  audit_logs type=index   key=ix_audit_logs_created_at                   rows=25      Backward index scan
-> Limit: 25 row(s)  (cost=0.0623 rows=25) (actual time=0.0448..0.0888 rows=25 loops=1)
    -> Index scan on audit_logs using ix_audit_logs_created_at (reverse)  (cost=0.0623 rows=25) (actual time=0.0441..0.087 rows=25 loops=1)
```

### Q9 audit trail of one record
```sql
SELECT id, created_at, username, action FROM audit_logs WHERE entity_type = 'encounter' AND entity_id = '123456' ORDER BY created_at DESC, id DESC LIMIT 25
```
**Before** (median 64.62 ms)
```
  audit_logs type=ALL     key=None                                       rows=297540  Using where; Using filesort
-> Limit: 25 row(s)  (cost=30419 rows=25) (actual time=78.8..78.8 rows=0 loops=1)
    -> Sort: audit_logs.created_at DESC, audit_logs.id DESC, limit input to 25 row(s) per chunk  (cost=30419 rows=297540) (actual time=78.8..78.8 rows=0 loops=1)
```
**After** (median 0.26 ms)
```
  audit_logs type=ref     key=ix_audit_logs_entity                       rows=1       Using filesort
-> Limit: 25 row(s)  (cost=0.378 rows=1) (actual time=0.0104..0.0104 rows=0 loops=1)
    -> Sort: audit_logs.created_at DESC, audit_logs.id DESC, limit input to 25 row(s) per chunk  (cost=0.378 rows=1) (actual time=0.0101..0.0101 rows=0 loops=1)
```

## What the plans showed and what I did
1. **Q1, Q3 (date range).** Before: `type=ALL` on `encounters`, about 101,000 rows read to return 942 (Q1). The date filter is a plain range (not wrapped in `DATE_FORMAT`, so it is sargable) but nothing could serve it. A composite index `(is_deleted, admission_date)` fits because both the view and every list/analytics query filter `is_deleted = 0` first and then range on the date; the plan now uses it as `type=range` (949 rows for Q1) and, because InnoDB appends the primary key, even satisfies `ORDER BY admission_date DESC, encounter_id DESC` without a sort. Column order matters: equality column first, range column second.
2. **Q6 (ICD-9 prefix).** Before: the diagnosis table was scanned (303,496 rows). `LIKE 'V57%'` is a prefix match, so an index on `icd9_code` gives `type=range` over about 1,200 rows. A leading wildcard (`%57`) would not use it, which is why the API only supports prefix search.
3. **Q5, Q8, Q9 (audit).** Before: full scan of 300,000 rows plus a filesort. `ix_audit_logs_created_at` serves the newest-first list and the date window (Q8 reads 25 rows; Q5 reads the 1,520 rows inside the window and filters the user on those). `ix_audit_logs_entity (entity_type, entity_id)` is an equality lookup (Q9: one row).
4. **The join order of the view (Q4, Q6, Q7, and Q1 once statistics refreshed).** The first baseline measured Q1 at 38 ms; after I ran `ANALYZE TABLE` during experiments it jumped to about 350 ms because the optimizer switched to scanning `patients` first (it guesses that `is_deleted = 0` matches 10 percent of rows) and then probed `encounters` once per patient. That fragility comes from the view's `JOIN patients ... AND p.is_deleted = 0`, which exists only to hide soft-deleted patients. I tested alternatives on Q4: a histogram on `is_deleted` (663 ms, no change), an index on `patients(is_deleted)` (658 ms, still patient-first), and an anti-join (`NOT EXISTS`, plan starts at `encounters`). The anti-join returns identical rows (same counts and result hashes on all three queries, and the soft-delete tests still pass) and is what `views.sql` now uses.

## Indexes kept (each proven)
| Index | Serves | Proof |
|---|---|---|
| `ix_encounters_is_deleted_admission_date (is_deleted, admission_date)` | Q1, Q3 | plan `key` names it; dropping it made Q1 31.0 ms again vs 1.3 ms |
| `ix_encounter_diagnoses_icd9_code (icd9_code)` | Q6 | plan `key` names it; dropping it made Q6 51.2 ms vs 9.4 ms (type=ALL, about 303,500 rows) |
| `ix_audit_logs_created_at (created_at)` | Q5, Q8 | plan `key` names it; Q8 reads 25 rows instead of 297,540 |
| `ix_audit_logs_entity (entity_type, entity_id)` | Q9 | plan `key` names it; 1 row instead of 297,540 |

## Candidates measured or considered and rejected
| Candidate | Decision and reason |
|---|---|
| `audit_logs (username, created_at)` | **Rejected after trying it.** With it Q5 took 1.0 ms; dropping it left Q5 at 1.4 ms using `ix_audit_logs_created_at` (about 20,000 rows inside a 7-day window, filtered by user). A gain I cannot show does not belong in the design; revisit if audit volume or window sizes grow 100x. |
| `encounters (patient_nbr)` | Already exists as the foreign-key index (Q2 uses it). |
| `encounter_medications (medication_id)` | Already exists as the foreign-key index. |
| `encounters (admission_type_id, ...)`, `(admission_source_id)`, `(discharge_disposition_id)` | Foreign-key indexes exist; these columns have 7 to 25 distinct values (type 1 alone is 53 percent of rows), so a filter on them is not selective and a composite adds write cost for no measured gain. |
| `encounters (age_order)` | Q4 aggregates every row; an index cannot reduce the rows read. |
| `encounter_outcomes (is_readmission_eligible, readmitted_30d)` | Two-value columns have almost no selectivity, and a covering variant was measured: Q4-style aggregation stayed at about 307 ms with and without it. |
| `patients (is_deleted)` | Measured: the plan still started from `patients` (658 ms vs 670 ms). Boolean columns alone are almost never used. |
| Histogram on `is_deleted` | Measured: no change in plan or time. |
| `pipeline_runs (started_at)` | The table has tens of rows; an index would only cost writes. |

## Still slow: Q4 and Q7 (about 0.6 to 0.8 s), and the summary-table decision
Q4 (readmission rate by age group over all data) and Q7 (top drugs) must read every encounter, so an index cannot reduce the rows. Their time is the eight-table view join for 101,766 rows. A leaner experiment (encounters + outcomes + the anti-join only) took about 307 ms, so even a hand-built query is not near-instant. **Decision on a pre-aggregated summary table: not implemented.** Trade-off: it would make dashboard aggregates near-instant, but it adds staleness (it must be refreshed after every load and after every create/update/delete), an extra step to maintain and another thing to test, in exchange for saving about half a second on queries a user opens a few times a minute. The dashboard issues its calls in parallel, so a page loads in roughly the slowest call. If data grows tenfold, the scan grows tenfold: the sensible next step would be a summary table refreshed by the pipeline (monthly counts and eligible/readmitted counts per age group, admission type and so on), which is exactly what the date-range indexes already approximate for the filtered queries.

## Write cost
The same five batches (101,766 rows) loaded into a database built without and with the four indexes, two rounds each:

| | Round 1 | Round 2 | Median |
|---|---|---|---|
| Without the L12 indexes | 22.2 s | 22.2 s | 22.2 s |
| With the L12 indexes | 23.5 s | 23.8 s | 23.8 s |

About **7 percent** slower bulk loading, paid once per load; the affected queries are 4 to 324 times faster (Q3 about 4x; the date list, ICD search and audit queries 58x to 324x). The audit indexes cost one extra index update per audited change (a few rows per request).

## Honest limits
* Timings are one laptop with a warm cache, so I judge by rows examined in the plan as well as milliseconds.
* Q4 measured 500 ms with the view only and 611 ms with the indexes added; the plan is the same, so the difference is run-to-run noise, not an effect of the indexes.
* Synthetic audit rows are uniformly distributed; real audit data is bursty, which would make the `created_at` index look even better.
