"""No secret or sensitive demographic may appear in logs, the audit trail or error bodies (guide L18).

The test drives real requests (good and bad logins, patient create/update/delete, invalid bodies, a forbidden call, an
export, a server error) while capturing EVERY log record at DEBUG level, then searches all captured text.
"""
from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.api.conftest import PASSWORDS, auth_header, login
from tests.api.helpers import add_encounter
from sqlalchemy.orm import Session
from datetime import date

SENSITIVE_VALUES = ["Caucasian", "AfricanAmerican", "Asian"]  # race values used below
PATIENT = {"patient_nbr": 910000001, "race": "AfricanAmerican", "gender": "Female"}


def test_logs_audit_and_errors_never_contain_secrets_or_demographics(client: TestClient, users_db: Engine, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    seen_bodies: list[str] = []

    admin = auth_header(client, "admin")
    token = admin["Authorization"].split(" ", 1)[1]
    ops = auth_header(client, "ops")
    ana = auth_header(client, "ana")

    seen_bodies.append(login(client, "admin", "Wrong-Password-Typed-1").text)        # failed login
    seen_bodies.append(client.post("/auth/login", data={"username": "ghost", "password": "Ghost-Password-1"}).text)
    seen_bodies.append(client.post("/auth/login", data={"username": "admin"}).text)  # 422
    seen_bodies.append(client.get("/patients", headers=ana).text)                    # 403
    seen_bodies.append(client.get("/encounters", headers={"Authorization": "Bearer not.a.token"}).text)  # 401

    assert client.post("/patients", json=PATIENT, headers=ops).status_code == 201
    assert client.put(f"/patients/{PATIENT['patient_nbr']}", json={"race": "Asian", "gender": "Unknown"}, headers=ops).status_code == 200
    seen_bodies.append(client.post("/patients", json={**PATIENT, "gender": "robot"}, headers=ops).text)  # 422 echoing nothing
    with Session(users_db) as s, s.begin():
        add_encounter(s, 910000100, 910000001, admission=date(2005, 3, 1), race="Caucasian")
    seen_bodies.append(client.get("/encounters", headers=ana).text)                  # analyst view
    assert client.get("/reports/export?report=encounters&format=csv", headers=ops).status_code == 200
    assert client.delete(f"/patients/{PATIENT['patient_nbr']}", headers=admin).status_code == 204

    # a server error must be generic in the response and must not log the request's secrets
    client.app.add_api_route("/_t/boom", lambda: 1 / 0)
    boom = client.get("/_t/boom", headers=admin)
    assert boom.status_code == 500
    seen_bodies.append(boom.text)
    assert "ZeroDivisionError" not in boom.text and "Traceback" not in boom.text and "line " not in boom.text.lower()

    with users_db.connect() as conn:
        audit_text = json.dumps([[str(c) for c in row] for row in conn.execute(text("SELECT * FROM audit_logs")).all()])

    logs = "\n".join(r.getMessage() for r in caplog.records) + "\n" + caplog.text
    haystacks = {"logs": logs, "audit trail": audit_text, "error bodies": "\n".join(seen_bodies)}
    secrets = list(PASSWORDS.values()) + ["Wrong-Password-Typed-1", "Ghost-Password-1", "Inactive-Pass-1", token, "$2b$", "$2a$",
                                           "password_hash", "Authorization", "Bearer not.a.token"]
    for where, text_ in haystacks.items():
        for secret in secrets:
            assert secret not in text_, f"{secret!r} found in {where}"
        for value in SENSITIVE_VALUES:
            assert value not in text_, f"race value {value!r} found in {where}"
    # demographics are never logged even as field names with values (race=..., 'gender': ...)
    for needle in ("'race'", '"race"', "'gender'", '"gender"', "race=", "gender="):
        assert needle not in logs and needle not in audit_text, f"{needle} found in logs or the audit trail"
