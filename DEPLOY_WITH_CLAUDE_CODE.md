# Deployment instructions for Claude Code

**Audience: Claude Code, running on a new machine, in a fresh clone of this repository.**
**Goal: get the Healthcare Patient Management System running locally and prove it works.**
Read this whole file first, then execute the steps in order. Do the checks; do not skip them. If a step fails, use the troubleshooting table (section 12) before improvising.

The project: Python (pandas, SQLAlchemy, FastAPI) + MySQL 8 + React (Vite) + optional Airflow. Everything runs locally. There is no Docker, no cloud and no CI/CD, and none must be added.

---

## 0. Ground rules (follow these throughout)

1. **Never commit or print secrets.** `.env` is git-ignored and must stay that way. Do not echo passwords or the JWT secret into the conversation, logs or any tracked file. When you must tell the user a password (the demo accounts), tell them once at the end.
2. **Ask the user** (do not guess) for: the MySQL administrator login if it is not already known, and whether to use generated or chosen demo passwords. Everything else you can decide.
3. **Never run the test-suite against the application database.** Tests use only a schema whose name ends in `_test` (the fixture refuses anything else). Do not change that.
4. **Do not modify application code** to make setup pass. If something cannot be fixed by configuration, stop and report it. Do not use `--force`, `--no-verify`, `git reset --hard` or destructive SQL (`DROP DATABASE`) on anything that existed before you started.
5. **Prefer 127.0.0.1 over `localhost`** everywhere (database URL, API, Vite). `localhost` can resolve to IPv6 only and break connections.
6. Dates in this data are **simulated** and the system is **educational only**; do not describe the data as real clinical dates or give clinical advice.
7. Work from the **repository root** unless a step says otherwise. Commands below use PowerShell (Windows) first, then bash (Linux/macOS).

Report progress after each numbered section with a one-line result (PASS/FAIL and the key number).

---

## 1. Check prerequisites

Detect the OS and check each tool. Tell the user what is missing and offer to install it (ask before installing system software).

| Tool | Needed | Check |
|---|---|---|
| Python | 3.11 or newer (3.12 tested) | `python --version` (Windows) / `python3 --version` |
| MySQL **8.x** server running on `127.0.0.1:3306` | **MySQL 8** specifically; MariaDB is not supported (the schema uses the `utf8mb4_0900_ai_ci` collation) | `mysql --version`; then `mysqladmin -h 127.0.0.1 ping` |
| Node.js | 20 or newer (24 tested) | `node --version` and `npm --version` |
| git | any | `git --version` |
| Chrome or Edge | only for the optional browser test and PDF rebuilding | optional |

Expected result: all required tools present. Stop and ask the user if MySQL is missing or not 8.x.

---

## 2. Python environment

Windows (PowerShell):
```powershell
python -m venv venv
.\venv\Scripts\python -m pip install --upgrade pip
.\venv\Scripts\pip install -r requirements.txt
```
Linux/macOS:
```bash
python3 -m venv venv
./venv/bin/python -m pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
```
Check: `venv python -c "import fastapi, pandas, sqlalchemy, pymysql, jwt, bcrypt, apscheduler, openpyxl; print('ok')"` prints `ok`.

Below, `PY` means the venv interpreter (`.\venv\Scripts\python` on Windows, `./venv/bin/python` on Linux/macOS). Always use it; never the system Python.

---

## 3. Download the dataset (it is not in the repository)

Source: UCI "Diabetes 130-US Hospitals for Years 1999-2008" (CC BY 4.0). Download and put `diabetic_data.csv` into `data/raw/`. (`data/reference/IDs_mapping.csv` is already in the repository.)

```powershell
# Windows
Invoke-WebRequest -Uri "https://archive.ics.uci.edu/static/public/296/diabetes+130-us+hospitals+for+years+1999-2008.zip" -OutFile "$env:TEMP\diabetes.zip"
Expand-Archive "$env:TEMP\diabetes.zip" "$env:TEMP\diabetes" -Force
Copy-Item "$env:TEMP\diabetes\diabetic_data.csv" data\raw\diabetic_data.csv
```
```bash
# Linux/macOS
curl -L -o /tmp/diabetes.zip "https://archive.ics.uci.edu/static/public/296/diabetes+130-us+hospitals+for+years+1999-2008.zip"
unzip -o /tmp/diabetes.zip -d /tmp/diabetes && cp /tmp/diabetes/diabetic_data.csv data/raw/
```
If the download fails (no internet or the URL changed), ask the user to download the dataset from https://archive.ics.uci.edu/dataset/296/diabetes+130-us+hospitals+for+years+1999-2008 and place `diabetic_data.csv` in `data/raw/`.

**Verify (required):** the file must have 101,766 data rows (101,767 lines including the header) and SHA-256
`0689E7EC031237DC63031B938805C48377748761A3B26ACAB621567AFA24DF97`.
- Windows: `(Get-FileHash data\raw\diabetic_data.csv).Hash`
- Linux/macOS: `sha256sum data/raw/diabetic_data.csv` (compare case-insensitively)

If the hash differs, stop and tell the user: the verification numbers in this document would not match.

---

## 4. MySQL: databases and application user

The project needs two schemas and one least-privilege user. `db/setup_database.sql` creates them and contains the placeholder password `CHANGE_ME`.

1. Ask the user for MySQL administrator access (usually `root`). If the user prefers, ask them to run the SQL themselves.
2. **Generate an application password** for the user `hc_app` (at least 20 random characters, letters and digits only, so it is URL-safe):
   `PY -c "import secrets,string; print(''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(24)))"`
   Keep it in a variable; you will need it for `.env`. Do not print it.
3. Run the SQL with the placeholder replaced, **without writing the password to any tracked file** (pipe it in):
   - Windows: `(Get-Content db\setup_database.sql -Raw).Replace('CHANGE_ME', $hcPwd) | mysql -u root -p --host=127.0.0.1`
   - Linux/macOS: `sed "s/CHANGE_ME/$HC_PWD/g" db/setup_database.sql | mysql -u root -p -h 127.0.0.1`

   It creates `healthcare_db`, `healthcare_test` and user `hc_app` (for `localhost` and `127.0.0.1`) with rights only on those two schemas.
4. Check: `mysql -h 127.0.0.1 -u hc_app -p -e "SHOW DATABASES LIKE 'healthcare%'"` lists both schemas.

If the user wants different schema names, the test schema name **must end in `_test`** and differ from the main one.

---

## 5. Configuration (`.env`)

Copy `.env.example` to `.env` (it is git-ignored) and fill in:

| Key | Value |
|---|---|
| `DATABASE_URL` | `mysql+pymysql://hc_app:<hc_app password>@127.0.0.1:3306/healthcare_db?charset=utf8mb4` |
| `TEST_DATABASE_URL` | same with `/healthcare_test` |
| `JWT_SECRET` | random, at least 32 characters: `PY -c "import secrets; print(secrets.token_urlsafe(48))"`. The API refuses to start with a missing, short or placeholder secret. |
| `ADMIN_PASSWORD`, `CLINICAL_OPS_PASSWORD`, `ANALYST_PASSWORD` | demo passwords, at least 12 characters, at most 72 bytes. Ask the user to choose, or generate and tell them at the end. If left empty, step 7 generates random ones and prints them once. |

Leave the other keys at their defaults. Check that `git status` does **not** list `.env`.

Smoke test (must show five PASS lines): `PY scripts/smoke_test.py`

---

## 6. Create tables, lookups, users and views

```
PY db/seed_reference.py        # creates all 16 tables (+ indexes) and loads the lookup tables
PY db/seed_users.py            # one user per role: admin, clinical_ops, analyst (bcrypt hashes)
PY scripts/apply_views.py      # v_active_encounters and v_readmission_base
```
All three are safe to repeat. `seed_users.py` never changes an existing user. If it prints `GENERATED PASSWORD`, record those passwords for the final report (do not log them elsewhere).

Check: `mysql ... healthcare_db -e "SHOW TABLES"` shows 16 tables plus 2 views.

---

## 7. Prepare and load the data

```
PY scripts/prepare_batches.py
```
Expected: `data/incoming/` gets `encounters_batch_000_initial.csv`, `..._001.csv`, `..._002.csv`; `data/held_back/` gets `..._003.csv` and `..._004.csv`.

Load. **The ETL module must be run from `src/`** (so `python -m` finds the `etl` package):
```powershell
cd src
..\venv\Scripts\python -m etl.pipeline --scan      # Windows
cd ..
```
```bash
cd src && ../venv/bin/python -m etl.pipeline --scan && cd ..     # Linux/macOS
```
Expected: three runs, all `SUCCESS` (81,412 + 5,089 + 5,089 rows, 0 rejected). The initial file takes about 12 seconds.

Add the two held-back batches and load again (this shows incremental loading):
copy `data/held_back/encounters_batch_003.csv` and `..._004.csv` into `data/incoming/`, then run the same `--scan` command. Expected: two more `SUCCESS` runs (5,088 rows each). Run `--scan` once more: it must report `scan found 0 new file(s)` (idempotent).

**Verify the numbers (required):**
```
PY scripts/verify_kpis.py
```
Expected last line: `88/88 checks passed` (it compares only the encounters that are loaded, so it works after any batch). Exit code 0.

Final state check (database): active encounters **101,766**; patients **71,518**; `pipeline_runs` has 5 `SUCCESS` rows. The headline 30-day readmission rate must be **0.113888** (11,314 / 99,343 eligible). If the rate differs, stop: the data or the rules are not what the project expects.

Optional failure demonstration (do this **after** the checks above, because it adds a sixth run to `pipeline_runs`): `PY scripts/make_faulty_batch.py` writes `data/incoming/faulty_batch.csv` and its JSON manifest `faulty_batch.json` (one backend test needs the manifest). Loading the CSV with `--scan` always quarantines exactly 23 rows into `data/rejected/faulty_batch_rejected.csv` (with a reason per row) and counts 5 corrected ICD codes; its other rows are batch-003 rows that already exist, so they are skipped. The run still reconciles. `PY scripts/make_faulty_batch.py --severe` writes `data/incoming/severe_faulty_batch.csv` (30% bad rows), which is refused whole (status FAILED, nothing loaded). Any CSV left in `data/incoming/` is picked up by the next `--scan`; delete the demonstration files afterwards if the user does not want them loaded.

---

## 8. Start the API

From `src/`:
```powershell
cd src
..\venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
```bash
cd src && ../venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Run it as a background/long-running process. Checks:
- `GET http://127.0.0.1:8000/health` returns `{"status":"ok","database":"up", ...}` with the latest pipeline run.
- `http://127.0.0.1:8000/docs` shows Swagger (HTTP 200).
- Log in: `POST /auth/login` with form fields `username=admin&password=<ADMIN_PASSWORD>` returns an access token; `GET /analytics/summary` with `Authorization: Bearer <token>` returns `total_encounters` 101766, `unique_patients` 71518, `readmission_rate_30d` 0.113888.
- As `analyst`, `GET /patients` must return **403**, and `GET /encounters` items must have no `patient_nbr`.

If the API will not start, read the message: a missing/weak `JWT_SECRET` or a wrong `DATABASE_URL` are the usual causes.

---

## 9. Start the front end

```
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173 (the API must be running on port 8000)
```
The dev server proxies `/api` to the API. Checks: `http://127.0.0.1:5173/` returns 200 and `http://127.0.0.1:5173/api/health` returns the health JSON. Sign in as `admin` (and as `analyst` to see the reduced menu). The dashboard shows 101,766 encounters, 71,518 patients, 30-day readmission 11.39% and a banner saying dates are simulated.

Front-end tests (no database or API needed): `npm test` expects **42 passed**.
Production build check (optional): `npm run build`.

---

## 10. Backend tests (about 11 minutes)

Make sure `data/incoming/faulty_batch.json` exists first (`PY scripts/make_faulty_batch.py`), otherwise one test is skipped.

```
PY -m pytest -q
```
Expected: **314 passed, 1 skipped** without the faulty-batch manifest, or **315 passed** with it. Optional coverage: `PY -m pytest --cov=src` (about 94%). The tests build and empty the `*_test` schema only; the loaded development data must be unchanged afterwards (re-check the 101,766 count).

Optional real-browser run (needs Chrome and both servers running): set `E2E_ADMIN_PASSWORD`, `E2E_OPS_PASSWORD`, `E2E_ANALYST_PASSWORD` to the demo passwords and run `node frontend/e2e/run.mjs`; expect **71/71 checks passed**. It rewrites `docs/screenshots/` and `docs/role_verification.md` (revert those with git if the user does not want changed files).

---

## 11. Optional: scheduling

- **Simplest (any OS):** `PY scripts/scheduler.py` runs the hourly load and the weekly report in one process (`--once etl` or `--once reports` runs one job now). Use this unless the user asks for Airflow.
- **Airflow (only if the user asks):** two DAGs are in `src/airflow/dags/` (`healthcare_incremental_etl`, `healthcare_weekly_report`). Airflow must live in its **own** virtualenv, never the project's one (its pinned packages break FastAPI). Use Airflow 3.1.x with the official constraints file. The DAGs call the project interpreter, which defaults to `venv/Scripts/python.exe`; **on Linux/macOS set `HC_PYTHON` to the absolute path of `venv/bin/python`** and set `HC_PROJECT_ROOT` to the repository root. `scripts/airflow_standalone.sh` was written for a WSL2 setup (`/opt/airflow-venv`); adapt its paths to the new machine. Full steps, demonstrated runs and recovery: `docs/runbook.md`.

---

## 12. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Can't connect to MySQL server on '127.0.0.1'` | MySQL not running, or wrong port. Start the server; check `mysqladmin -h 127.0.0.1 ping`. |
| `Unknown collation: 'utf8mb4_0900_ai_ci'` | The server is MariaDB or MySQL 5.7. Install MySQL 8. |
| `Access denied for user 'hc_app'` | Password in `.env` differs from step 4, or the grants were not applied. Re-run the SQL step with the same password. |
| API exits with `JWT_SECRET ...` | Set a random secret of 32+ characters in `.env`. |
| `No module named 'etl'` | Run the pipeline from `src/` (`cd src` then `python -m etl.pipeline ...`), or set `PYTHONPATH=src`. |
| `ReferenceDataError: Reference tables are empty` | Run `db/seed_reference.py` first (step 6). |
| `verify_kpis.py` prints FAIL lines | The loaded data or `data/raw` differs from expectations. Check the dataset hash (step 3) and that all runs are `SUCCESS`. Do not edit the rules to make it pass. |
| Run `FAILED` with `reject ratio ... exceeds` | The input file is more than 20% bad; this is by design (nothing loads). Inspect `data/rejected/`. |
| Browser shows a blank page or network errors | The API is not running on port 8000, or Vite was opened via `localhost`. Use `http://127.0.0.1:5173`. |
| `npm install` fails | Check Node is 20 or newer; delete `frontend/node_modules` and retry. |
| One test skipped | `data/incoming/faulty_batch.json` missing; run `make_faulty_batch.py`. |
| Tests fail with `Refusing to run tests against database` | `TEST_DATABASE_URL` points at a schema that does not end in `_test` or equals `DATABASE_URL`. Fix `.env`. |
| `ModuleNotFoundError` for packages | You used the system Python; use the venv interpreter. |
| Windows: PowerShell does not accept `&&` | Windows PowerShell 5.1 has no `&&`; run commands on separate lines or use `;`. |

---

## 13. Expected end state (what to report to the user)

| Item | Expected |
|---|---|
| Tables / views | 16 tables, 2 views |
| `pipeline_runs` | 5 SUCCESS (81,412; 5,089; 5,089; 5,088; 5,088 rows) |
| Active encounters / patients | 101,766 / 71,518 |
| 30-day readmission rate | 0.113888 (11,314 / 99,343 eligible) |
| `verify_kpis.py` | 88/88 checks passed |
| API | `/health` ok, `/docs` 200, analyst gets 403 on `/patients` |
| Front end | `http://127.0.0.1:5173` works; `npm test` 42 passed |
| Backend tests | 314 passed + 1 skipped (315 passed with the faulty-batch manifest) |
| `git status` | clean apart from ignored files; `.env` not tracked |

When finished, give the user: (1) the URLs (`http://127.0.0.1:5173` for the app, `http://127.0.0.1:8000/docs` for Swagger), (2) the usernames `admin`, `clinical_ops`, `analyst` and, **once**, any generated passwords, (3) how to start both servers again, (4) anything that did not match the expected values, and (5) a reminder that the dates are simulated and the project is for education only. Do not leave servers running unless the user wants that.

---

## 14. Reference

- `README.md`: the same setup for humans, plus sample API requests.
- `docs/runbook.md`: operations, recovery and Airflow details.
- `docs/data_contract.md`: the rules every layer follows (read before changing anything).
- `docs/API_Documentation.pdf`, `docs/test_report.md`, `design/Design_Document.pdf`.
- `CLAUDE.md`: coding rules for this repository (read before editing code).
