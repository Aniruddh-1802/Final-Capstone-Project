# Healthcare Patient Management System - project context
Educational capstone. Dataset: UCI Diabetes 130-US Hospitals 1999-2008 (diabetic_data.csv + IDs_mapping.csv).
Educational use only. Do not expose unnecessary personal attributes (race, gender).

## Stack
Python 3.11, pandas, SQLAlchemy 2.0 (sync), PyMySQL, MySQL 8, FastAPI, Pydantic v2, pytest,
Apache Airflow (scheduling only, separate virtualenv), React + Vite + Recharts + axios + react-router.
NO Docker, NO cloud deployment, NO CI/CD. PySpark is not used unless I ask.

## Layout
Python root is src/. Packages: app (api), etl, utils, airflow/dags. Also db/, scripts/, frontend/, tests/, docs/, data/.

## Data contract (must always be respected)
- Raw grain: one row = one encounter. encounter_id is unique. patient_nbr repeats (patients != encounters).
- '?' means missing. Read CSV with keep_default_na=False and na_values=['?','']. The text 'None' in
  max_glu_serum and A1Cresult is a real value (test not performed), not missing.
- weight (~97% missing), examide and citoglipton (constant) are not loaded.
- admission_date is SIMULATED (seeded; the dataset has no dates). discharge_date = admission_date + time_in_hospital.
  Always label simulated dates in UI, API meta and docs.
- readmitted is 'NO' | '>30' | '<30'. readmitted_30d = (readmitted == '<30').
- is_readmission_eligible = False when discharge_disposition_id in (11,13,14,19,20,21) (expired/hospice).
  Every readmission rate uses eligible encounters as the denominator.
- age is a bracket string like '[70-80)'. Keep age_order (1-10) and sort by it, never alphabetically.
- ICD-9 codes (diag_1..3) are strings. Never cast to float.
- Medications: store only Steady/Up/Down rows in encounter_medications; 'No' is not stored.
- Soft delete via is_deleted. EVERY list, analytics and export query must exclude deleted rows.
- No hospital identifier exists. Never invent hospitals; use encounter categories.

## Roles: administrator, clinical_ops, analyst (permission matrix is in docs/data_contract.md)

## Engineering rules
- Type hints and docstrings. logging, never print. No secrets in code or git; config comes from .env.
- SQLAlchemy ORM/Core with bound parameters only (no string-built SQL).
- Error JSON: {"error": {"code": str, "message": str, "details": any}}.
- List responses: {"items": [...], "total": int, "page": int, "page_size": int, "pages": int}.
- Tests with pytest (pythonpath = src). Every new module that has logic gets tests.

## Working agreement
- For anything larger than one function, show a plan or file list first and wait for approval.
- Inspect existing code before creating new abstractions. Do not duplicate logic.
- State assumptions explicitly. After changes, tell me exactly how to verify them.

## Deploying on a new machine
If asked to set this project up on a new system, follow `DEPLOY_WITH_CLAUDE_CODE.md` step by step (prerequisites, dataset download with hash check, MySQL, .env, seeding, loading, API, front end, tests) and verify each step's expected result.
