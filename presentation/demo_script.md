# Demo script (8 minutes demo + 2 minutes questions)

Practise twice with a stopwatch. Cut content, not pace. Say it every time: **admission dates are simulated; findings are associations, not causes.**

## Before you start (5 minutes, off the clock)
1. MySQL running. Terminal 1: `cd src` then `uvicorn app.main:app` (API). Terminal 2: `cd frontend` then `npm run dev` (UI, http://127.0.0.1:5173).
2. Database state for the live load: batch 003 or 004 **not yet loaded**. On the dev database all five batches are loaded, so for the live step use the faulty batch and the severe file (both load nothing new) or a fresh database (README steps 7-9 load 000-002; copy 003 into `data/incoming` live).
3. Open in tabs: Architecture_Diagram.png, `docs/erd.png`, http://127.0.0.1:8000/docs, the dashboard (logged in as `admin`), a private window for `analyst`.
4. Have `docs/performance_notes.md` (Q1 and Q6 plans) and `docs/test_report.md` open.
5. Fallback: `docs/screenshots/` has every screen; `docs/runbook.md` has the demonstrated Airflow runs.

## Timed script
| Time | Segment | What to show and say |
|---|---|---|
| 0:00-0:45 | Problem and questions | The four business questions. One line on the data: 101,766 encounters, 71,518 patients, no dates and no hospital id, so dates are simulated and we compare categories. |
| 0:45-1:45 | Architecture | Architecture_Diagram: dataset to ETL to MySQL to API to React; Airflow triggers ETL and reports; quality rules live in the ETL, audit in the API, quarantine and logs on the side. |
| 1:45-3:00 | ETL and quality | `cd src` then `python -m etl.pipeline --scan` with batch 003 in `data/incoming` (about 1 s). Show the `pipeline_runs` row on the Pipeline Runs page: read = loaded + rejected + skipped. Run it again: no-op. Load `faulty_batch.csv`: 23 rows quarantined, open the Data Quality page for the reasons. Mention the severe file refused whole (20% rule). |
| 3:00-3:45 | Database | `docs/erd.png`: race and gender only on `patients`; third normal form. One plan: Q1 date-range list 256 ms to 0.8 ms with `ix_encounters_is_deleted_admission_date`. |
| 3:45-5:15 | API | Swagger: log in, `GET /encounters` filtered (`age_group=[90-100)`, `readmitted=<30`) and paged; try as analyst on `/patients`: 403; `PUT /encounters/{id}` then `GET /admin/audit-logs?entity_id=...`: the row shows only changed fields. |
| 5:15-7:15 | Dashboard | Answer the four questions with filters; point at the simulated-dates banner; prior visits 0 vs 3+: 8.6% vs 26.4% (associated with); switch to the analyst window: no patient column, no Patients menu; export Excel from Reports. |
| 7:15-8:00 | Testing and limits | `pytest` result and coverage from `docs/test_report.md`; the deliberate-bug check (6 tests fail); limitations (simulated dates, no hospital id, observational) and next steps. |
| 8:00-10:00 | Questions | Appendix F answers: denominator, idempotency, indexes, RBAC on the server, audit in the same transaction, scaling 100x. |

## Recording the 5-7 minute video
Record the same flow at a calmer pace (screen capture with voice; Windows: Win+G, or any recorder), export MP4, upload privately (Google Drive or YouTube unlisted) and paste the link into `presentation/demo_video_link.txt`.
