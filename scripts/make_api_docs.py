"""Generate docs/API_Documentation.md from /openapi.json plus REAL calls against the running app and dev database.

Every sample request and response in the output was produced by this script (nothing is typed by hand). Passwords come
from .env and are never written to the document; tokens are shortened. Write samples create a sample patient and
encounter and soft-delete them again, and create then deactivate one sample user.

Run from the repository root:  python scripts/make_api_docs.py
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
logging.disable(logging.CRITICAL)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database import get_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.permissions import PERMISSIONS  # noqa: E402
from app.security import hash_password  # noqa: E402

OUT = ROOT / "docs" / "API_Documentation.md"
BASE = "http://127.0.0.1:8000"
MAX_ITEMS = 2          # list items shown in a sample response

# capability needed per operation (None = public, "auth" = any signed-in user)
CAPABILITY: dict[tuple[str, str], str | None] = {
    ("POST", "/auth/login"): None, ("GET", "/auth/me"): "auth", ("GET", "/health"): None,
    ("POST", "/patients"): "write_records", ("GET", "/patients"): "view_patients", ("GET", "/patients/{patient_nbr}"): "view_patients",
    ("PUT", "/patients/{patient_nbr}"): "write_records", ("DELETE", "/patients/{patient_nbr}"): "delete_records",
    ("GET", "/patients/{patient_nbr}/encounters"): "view_patients",
    ("POST", "/encounters"): "write_records", ("GET", "/encounters"): "list_encounters", ("GET", "/encounters/{encounter_id}"): "list_encounters",
    ("PUT", "/encounters/{encounter_id}"): "write_records", ("DELETE", "/encounters/{encounter_id}"): "delete_records",
    ("GET", "/reports/export"): "export_aggregated", ("GET", "/reports/history"): "view_pipeline",
    ("GET", "/admin/audit-logs"): "view_audit", ("GET", "/admin/pipeline-runs"): "view_pipeline", ("GET", "/admin/dq-issues"): "view_pipeline",
    ("GET", "/admin/users"): "manage_users", ("POST", "/admin/users"): "manage_users",
}
for _p in ("summary", "admissions-trend", "length-of-stay", "readmissions", "medications", "utilization"):
    CAPABILITY[("GET", f"/analytics/{_p}")] = "dashboards"
for _p in ("admission-types", "admission-sources", "discharge-dispositions", "specialties", "age-groups"):
    CAPABILITY[("GET", f"/reference/{_p}")] = "auth"

client = TestClient(app)
tokens: dict[str, str] = {}
samples: dict[tuple[str, str], dict[str, Any]] = {}       # (METHOD, template) -> {"request": str, "status": int, "body": str, "note": str}
extra_samples: list[dict[str, Any]] = []                  # error and role examples


def short_token(tok: str) -> str:
    return tok[:18] + "..." + tok[-6:]


def trim(value: Any, notes: list[str]) -> Any:
    """Shorten long lists in a sample response (and say so)."""
    if isinstance(value, list):
        if len(value) > MAX_ITEMS:
            notes.append(f"a list of {len(value)} items is shortened to {MAX_ITEMS}")
        return [trim(v, notes) for v in value[:MAX_ITEMS]]
    if isinstance(value, dict):
        return {k: trim(v, notes) for k, v in value.items()}
    return value


def render(resp) -> tuple[str, str]:
    ctype = resp.headers.get("content-type", "")
    notes: list[str] = []
    if "json" in ctype:
        data = resp.json()
        if isinstance(data, dict) and "access_token" in data:
            data = {**data, "access_token": short_token(data["access_token"])}
        body = json.dumps(trim(data, notes), indent=2, ensure_ascii=False)
    elif not resp.content:
        body = "(empty body)"
    elif "csv" in ctype or "text" in ctype:
        body = "\n".join(resp.text.splitlines()[:6])
        notes.append("first lines of the file")
    else:
        body = f"(binary file, {len(resp.content):,} bytes, content-type {ctype})"
    return body, "; ".join(sorted(set(notes)))


def call(role: str | None, method: str, url: str, *, key: str | None = None, template: str | None = None, json_body: Any = None,
         form: dict | None = None, label: str | None = None, show_body: Any = None, **kw):
    headers = {"Authorization": f"Bearer {tokens[role]}"} if role else {}
    resp = client.request(method, url, headers=headers, json=json_body, data=form, **kw)
    curl = f"curl -X {method}" + ("" if role is None else ' -H "Authorization: Bearer $TOKEN"')
    if json_body is not None:
        curl += ' -H "Content-Type: application/json" -d \'' + json.dumps(show_body if show_body is not None else json_body) + "'"
    if form is not None:
        curl += " -d " + " -d ".join(f'"{k}={v if k != "password" else "<password>"}"' for k, v in form.items())
    curl += f' "{BASE}{resp.request.url.raw_path.decode()}"'   # the URL actually sent, query string included
    body, note = render(resp)
    record = {"request": curl, "status": resp.status_code, "body": body, "note": note, "role": role or "(no token)", "label": label}
    if template:
        samples[(method, template)] = record
    else:
        extra_samples.append(record)
    return resp


def free_id(table: str, column: str, start: int) -> int:
    with get_engine().connect() as conn:
        used = {r[0] for r in conn.execute(text(f"SELECT {column} FROM {table} WHERE {column} >= :s"), {"s": start})}
    while start in used:
        start += 1
    return start


def run_samples() -> None:
    # The documented calls use throwaway accounts (random passwords, deactivated at the end) so no real credential is needed.
    tag = secrets.token_hex(3)
    passwords: dict[str, str] = {}
    with get_engine().begin() as conn:
        for role in ("administrator", "clinical_ops", "analyst"):
            passwords[role] = secrets.token_urlsafe(14)
            conn.execute(text("INSERT INTO app_users (username, password_hash, role, is_active) VALUES (:u, :h, :r, 1)"),
                         {"u": f"docs_{role}_{tag}", "h": hash_password(passwords[role]), "r": role})
    for role in ("administrator", "clinical_ops", "analyst"):
        username = f"docs_{role}_{tag}"
        r = client.post("/auth/login", data={"username": username, "password": passwords[role]})
        r.raise_for_status()
        tokens[role] = r.json()["access_token"]
        if role == "administrator":
            call(None, "POST", "/auth/login", template="/auth/login", form={"username": username, "password": passwords[role]})
            samples[("POST", "/auth/login")]["body"] = json.dumps({**r.json(), "access_token": short_token(tokens[role])}, indent=2)

    call("administrator", "GET", "/auth/me", template="/auth/me")
    call(None, "GET", "/health", template="/health")

    # ---- patients and encounters: create, read, update, delete (a sample record that is soft-deleted again) -----------------
    pid = free_id("patients", "patient_nbr", 990000001)
    eid = free_id("encounters", "encounter_id", 990000001)
    call("clinical_ops", "POST", "/patients", template="/patients", json_body={"patient_nbr": pid, "race": "Caucasian", "gender": "Female"})
    call("clinical_ops", "PUT", f"/patients/{pid}", template="/patients/{patient_nbr}", json_body={"gender": "Unknown"})
    enc = {"encounter_id": eid, "patient_nbr": pid, "admission_date": "2005-03-01", "discharge_date": "2005-03-04", "age_group": "[70-80)",
           "admission_type_id": 1, "discharge_disposition_id": 1, "admission_source_id": 7, "medical_specialty": "Cardiology", "payer_code": "MC",
           "time_in_hospital": 3, "num_lab_procedures": 40, "num_procedures": 1, "num_medications": 12, "number_outpatient": 0,
           "number_emergency": 0, "number_inpatient": 0, "number_diagnoses": 3, "max_glu_serum": "None", "a1c_result": "None",
           "med_changed": False, "diabetes_med": True, "readmitted": "NO",
           "diagnoses": [{"position": 1, "icd9_code": "250.83"}, {"position": 2, "icd9_code": "401.9"}],
           "medications": [{"drug_name": "insulin", "dosage_status": "Steady"}]}
    call("clinical_ops", "POST", "/encounters", template="/encounters", json_body=enc)
    call("clinical_ops", "PUT", f"/encounters/{eid}", template="/encounters/{encounter_id}", json_body={"readmitted": "<30", "number_inpatient": 1})
    call("administrator", "GET", f"/patients/{pid}", template="/patients/{patient_nbr}")
    samples[("GET", "/patients/{patient_nbr}")]["label"] = "get"
    call("administrator", "GET", "/patients", template="/patients", params={"q": "99000", "page_size": 2})
    call("administrator", "GET", f"/patients/{pid}/encounters", template="/patients/{patient_nbr}/encounters")
    call("clinical_ops", "GET", f"/encounters/{eid}", template="/encounters/{encounter_id}", label="get")
    call("administrator", "GET", "/encounters", template="/encounters",
         params={"age_group": "[90-100)", "readmitted": "<30", "sort_by": "time_in_hospital", "sort_dir": "desc", "page_size": 2})
    call("analyst", "GET", "/encounters", label="Same request as an analyst: the response is data-minimised (no patient_nbr, race or gender)",
         params={"age_group": "[90-100)", "readmitted": "<30", "sort_by": "time_in_hospital", "sort_dir": "desc", "page_size": 2})
    call("analyst", "GET", "/patients", label="An analyst calling a patient endpoint is refused (403), whatever the interface hides")
    call("administrator", "GET", "/admin/audit-logs", template="/admin/audit-logs", params={"entity_id": str(eid), "page_size": 5, "sort_dir": "asc"})
    call("clinical_ops", "DELETE", f"/encounters/{eid}", label="clinical_ops cannot delete (403): only administrators can")
    call("administrator", "DELETE", f"/encounters/{eid}", template="/encounters/{encounter_id}")
    call("administrator", "DELETE", f"/patients/{pid}", template="/patients/{patient_nbr}")
    call("administrator", "GET", f"/encounters/{eid}", label="A soft-deleted encounter is invisible: 404, like an id that never existed")

    # ---- errors ----------------------------------------------------------------------------------------------------------------------
    call(None, "GET", "/encounters", label="No token: 401")
    call("clinical_ops", "POST", "/encounters", label="Invalid body: 422 with field-level details", json_body={**enc, "encounter_id": eid + 1, "time_in_hospital": 40,
                                                                                                          "discharge_date": "2005-02-01"})
    call("administrator", "GET", "/encounters", label="Unknown sort column is refused, never passed to SQL: 422", params={"sort_by": "password_hash"})

    # ---- analytics, reports, admin, reference -------------------------------------------------------------------------------------
    call("analyst", "GET", "/analytics/summary", template="/analytics/summary")
    call("analyst", "GET", "/analytics/admissions-trend", template="/analytics/admissions-trend", params={"granularity": "year"})
    call("analyst", "GET", "/analytics/length-of-stay", template="/analytics/length-of-stay", params={"group_by": "age_group"})
    call("analyst", "GET", "/analytics/readmissions", template="/analytics/readmissions", params={"group_by": "age_group"})
    call("analyst", "GET", "/analytics/medications", template="/analytics/medications")
    call("analyst", "GET", "/analytics/utilization", template="/analytics/utilization")
    call("analyst", "GET", "/reports/export", template="/reports/export", params={"report": "readmission_summary", "format": "csv"})
    call("analyst", "GET", "/reports/export", label="An analyst may not export encounter-level data (403)", params={"report": "encounters", "format": "csv"})
    call("clinical_ops", "GET", "/reports/history", template="/reports/history", params={"page_size": 2})
    call("clinical_ops", "GET", "/admin/pipeline-runs", template="/admin/pipeline-runs", params={"page_size": 2})
    call("clinical_ops", "GET", "/admin/dq-issues", template="/admin/dq-issues", params={"page_size": 2})
    call("administrator", "GET", "/admin/users", template="/admin/users", params={"page_size": 3})
    sample_user = "docs_sample_" + secrets.token_hex(3)
    secret = secrets.token_urlsafe(14)
    call("administrator", "POST", "/admin/users", template="/admin/users", json_body={"username": sample_user, "password": secret, "role": "analyst"},
         show_body={"username": sample_user, "password": "<at least 12 characters>", "role": "analyst"})
    with get_engine().begin() as conn:      # leave no usable sample account behind
        conn.execute(text("UPDATE app_users SET is_active = 0 WHERE username = :u"), {"u": sample_user})
    for ref in ("admission-types", "admission-sources", "discharge-dispositions", "specialties", "age-groups"):
        call("analyst", "GET", f"/reference/{ref}", template=f"/reference/{ref}")
    with get_engine().begin() as conn:      # the throwaway accounts cannot be used again
        conn.execute(text("UPDATE app_users SET is_active = 0 WHERE username LIKE :p"), {"p": f"docs\\_%\\_{tag}"})


# ---- document ----------------------------------------------------------------------------------------------------------------------------------------
def resolve(spec: dict, schema: dict) -> dict:
    if "$ref" in schema:
        return spec["components"]["schemas"][schema["$ref"].split("/")[-1]]
    return schema


def type_of(spec: dict, s: dict) -> str:
    if "$ref" in s:
        return s["$ref"].split("/")[-1]
    if "anyOf" in s:
        return " or ".join(sorted({type_of(spec, x) for x in s["anyOf"] if x.get("type") != "null"})) or "null"
    if s.get("enum"):
        return "one of: " + ", ".join(f"`{e}`" for e in s["enum"])
    t = s.get("type", "any")
    if t == "array":
        return f"array of {type_of(spec, s.get('items', {}))}"
    bounds = [f"{k} {s[k]}" for k in ("minimum", "maximum", "exclusiveMinimum", "minLength", "maxLength", "default") if k in s]
    return t + (f" ({', '.join(bounds)})" if bounds else "")


def roles_text(cap: str | None) -> str:
    if cap is None:
        return "public (no token)"
    if cap == "auth":
        return "any signed-in user"
    return ", ".join(sorted(PERMISSIONS[cap]))


def block(rec: dict) -> list[str]:
    lines = [f"Request ({rec['role']}):", "```bash", rec["request"], "```", f"Response `{rec['status']}`" + (f" ({rec['note']})" if rec["note"] else "") + ":",
             "```json" if rec["body"].lstrip().startswith(("{", "[")) else "```text", rec["body"], "```"]
    return lines


def build() -> str:
    spec = app.openapi()
    out = ["# API Documentation", "",
           f"**{spec['info']['title']}**, version {spec['info']['version']}. Interactive Swagger UI: `{BASE}/docs`; machine-readable contract: `{BASE}/openapi.json`.", "",
           "This document is generated by `scripts/make_api_docs.py` from the running application's OpenAPI document and from real calls "
           "against the development database (101,766 encounters). Admission and discharge dates in this data are **simulated**; every readmission "
           "rate uses *eligible* encounters (expired and hospice discharges excluded) as the denominator. Educational use only.", "",
           "## 1. Conventions", "",
           "| Topic | Rule |", "|---|---|",
           "| Authentication | `POST /auth/login` (form fields `username`, `password`) returns a bearer token (HS256 JWT, valid 60 minutes). Send `Authorization: Bearer <token>`. In the samples below `$TOKEN` is that token. |",
           "| Roles | `administrator`, `clinical_ops`, `analyst`. Roles are enforced on the server for every request; the table in section 2 is the single source (`app/permissions.py`). |",
           "| Error body | `{\"error\": {\"code\": \"...\", \"message\": \"...\", \"details\": ...}}` for every error. Common codes: 401 `unauthorized`, 403 `forbidden`, 404 `not_found`, 409 `conflict`, 422 `validation_error`, 413 `too_large`. No stack trace or SQL is ever returned. |",
           "| Request id | Every response carries `X-Request-ID`; the same id is on each log line for that request. |",
           "| Lists | `{\"items\": [...], \"total\": n, \"page\": n, \"page_size\": n, \"pages\": n, \"meta\": {...}}`. `page` starts at 1, `page_size` defaults to 25 and is capped at 100. Sorting uses a whitelist of columns plus a unique tie-breaker, so pages never repeat or skip rows. |",
           "| Deletes | `DELETE` is a soft delete (`is_deleted`): the record disappears from lists, analytics and exports, and the change is audited. |",
           "| Analytics | Responses are `{\"data\": ..., \"meta\": {...}}`. `meta` states the denominator and `dates_simulated: true`. Groups with fewer than 11 encounters are flagged `small_n`. |",
           "| Audit | Every create, update, delete and export writes an `audit_logs` row in the same database transaction as the change. |", "",
           "## 2. Who can call what (permission matrix)", "",
           "| Capability | Roles allowed |", "|---|---|"]
    for cap, roles in PERMISSIONS.items():
        out.append(f"| `{cap}` | {', '.join(sorted(roles))} |")
    out += ["", "Analysts calling `GET /encounters` receive a minimised response without `patient_nbr`, race or gender.", "", "## 3. Endpoints", ""]
    index = ["| Method | Path | Roles | Summary |", "|---|---|---|---|"]
    detail: list[str] = []
    n = 0
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            m = method.upper()
            cap = CAPABILITY[(m, path)]
            roles = roles_text(cap)
            if (m, path) == ("GET", "/reports/export"):
                roles = "aggregated reports: all roles; `report=encounters`: " + ", ".join(sorted(PERMISSIONS["export_encounters"]))
            n += 1
            summary = op.get("summary", "")
            index.append(f"| {m} | `{path}` | {roles} | {summary} |")
            detail += [f"### 3.{n} `{m} {path}`", "", f"{summary}.", "", f"**Roles allowed:** {roles}", ""]
            params = op.get("parameters", [])
            if params:
                detail += ["**Parameters**", "", "| Name | In | Type | Required | Notes |", "|---|---|---|---|---|"]
                for p in params:
                    detail.append(f"| `{p['name']}` | {p['in']} | {type_of(spec, p.get('schema', {}))} | {'yes' if p.get('required') else 'no'} | {(p.get('description') or '').replace(chr(10), ' ')} |")
                detail.append("")
            body = op.get("requestBody")
            if body:
                ctype, content = next(iter(body["content"].items()))
                schema = resolve(spec, content["schema"])
                detail += [f"**Request body** (`{ctype}`)", "", "| Field | Type | Required |", "|---|---|---|"]
                req = set(schema.get("required", []))
                for fname, fs in schema.get("properties", {}).items():
                    if fname in ("grant_type", "scope", "client_id", "client_secret"):
                        continue
                    detail.append(f"| `{fname}` | {type_of(spec, fs)} | {'yes' if fname in req else 'no'} |")
                detail.append("")
            codes = ", ".join(f"`{c}`" for c in op["responses"])
            ok = next(iter(op["responses"]))
            rs = op["responses"][ok].get("content", {}).get("application/json", {}).get("schema")
            detail += [f"**Response format:** success `{ok}`" + (f", body `{type_of(spec, rs)}`" if rs else ", no body") + f". Declared status codes: {codes}.", ""]
            rec = samples.get((m, path))
            if rec:
                detail += ["**Sample (real call)**", ""] + block(rec) + [""]
    out += index + [""] + detail
    out += ["## 4. Role and error examples (real calls)", ""]
    for i, rec in enumerate(extra_samples, 1):
        out += [f"### 4.{i} {rec['label']}", ""] + block(rec) + [""]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    run_samples()
    OUT.write_text(build(), encoding="utf-8")
    sys.stdout.write(f"wrote {OUT.relative_to(ROOT)}: {len(samples)} endpoint samples, {len(extra_samples)} role/error examples\n")
