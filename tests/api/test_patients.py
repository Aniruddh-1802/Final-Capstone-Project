"""Patient CRUD: roles per the permission matrix, validation, soft delete, audit rows."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.api.conftest import auth_header
from tests.api.helpers import add_encounter

BODY = {"patient_nbr": 900000001, "race": "Caucasian", "gender": "Female"}


def audit_rows(db: Engine, entity_type: str = "patient") -> list:
    with db.connect() as conn:
        return conn.execute(text("SELECT action, entity_id, username, role, before_json, after_json FROM audit_logs "
                                 "WHERE entity_type = :t ORDER BY id"), {"t": entity_type}).all()


def test_create_get_update_delete_cycle_as_administrator(client: TestClient, users_db: Engine) -> None:
    h = auth_header(client, "admin")
    r = client.post("/patients", json=BODY, headers=h)
    assert r.status_code == 201 and r.json()["patient_nbr"] == 900000001 and r.json()["race"] == "Caucasian"
    assert client.get("/patients/900000001", headers=h).json()["gender"] == "Female"
    r = client.put("/patients/900000001", json={"gender": "Unknown"}, headers=h)
    assert r.status_code == 200 and r.json()["gender"] == "Unknown" and r.json()["race"] == "Caucasian"
    assert client.delete("/patients/900000001", headers=h).status_code == 204
    for call in (client.get, client.delete):
        assert call("/patients/900000001", headers=h).status_code == 404
    assert client.put("/patients/900000001", json={"race": "x"}, headers=h).status_code == 404
    assert [r_[0] for r_ in audit_rows(users_db)] == ["CREATE", "UPDATE", "DELETE"]


def test_role_matrix_for_patients(client: TestClient, users_db: Engine) -> None:
    admin, ops, ana = (auth_header(client, n) for n in ("admin", "ops", "ana"))
    client.post("/patients", json=BODY, headers=admin)
    # clinical_ops: create, read, update, list yes; delete no
    assert client.post("/patients", json={**BODY, "patient_nbr": 900000002}, headers=ops).status_code == 201
    assert client.get("/patients/900000002", headers=ops).status_code == 200
    assert client.put("/patients/900000002", json={"race": "Asian"}, headers=ops).status_code == 200
    assert client.get("/patients", headers=ops).status_code == 200
    assert client.delete("/patients/900000002", headers=ops).status_code == 403
    # analyst: no patient endpoint at all, race and gender never reachable
    for method, url, kw in (("GET", "/patients", {}), ("GET", "/patients/900000001", {}),
                            ("GET", "/patients/900000001/encounters", {}), ("POST", "/patients", {"json": BODY}),
                            ("PUT", "/patients/900000001", {"json": {"race": "x"}}),
                            ("DELETE", "/patients/900000001", {})):
        r = client.request(method, url, headers=ana, **kw)
        assert r.status_code == 403, f"{method} {url}"
        assert "Caucasian" not in r.text
    # no token at all
    assert client.get("/patients/900000001").status_code == 401


def test_duplicate_patient_is_409_even_after_soft_delete(client: TestClient) -> None:
    h = auth_header(client, "admin")
    assert client.post("/patients", json=BODY, headers=h).status_code == 201
    dup = client.post("/patients", json=BODY, headers=h)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "conflict"
    client.delete("/patients/900000001", headers=h)
    assert client.post("/patients", json=BODY, headers=h).status_code == 409


@pytest.mark.parametrize("body, field", [
    ({"patient_nbr": -5}, "patient_nbr"), ({"patient_nbr": 0}, "patient_nbr"), ({}, "patient_nbr"),
    ({"patient_nbr": 5, "gender": "Other"}, "gender"), ({"patient_nbr": 5, "race": "x" * 31}, "race"),
    ({"patient_nbr": "abc"}, "patient_nbr"),
])
def test_invalid_create_is_422_with_field_level_details(client: TestClient, body: dict, field: str) -> None:
    r = client.post("/patients", json=body, headers=auth_header(client, "admin"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    assert any(field in d["loc"] for d in r.json()["error"]["details"])


def test_update_validation_and_explicit_null(client: TestClient) -> None:
    h = auth_header(client, "admin")
    client.post("/patients", json=BODY, headers=h)
    assert client.put("/patients/900000001", json={}, headers=h).status_code == 422  # nothing to change
    assert client.put("/patients/900000001", json={"gender": "robot"}, headers=h).status_code == 422
    r = client.put("/patients/900000001", json={"race": None}, headers=h)
    assert r.status_code == 200 and r.json()["race"] is None and r.json()["gender"] == "Female"


def test_unknown_patient_is_404_with_error_contract(client: TestClient) -> None:
    r = client.get("/patients/123456", headers=auth_header(client, "admin"))
    assert r.status_code == 404 and set(r.json()["error"]) == {"code", "message", "details"}


def test_patient_encounters_endpoint_and_soft_deleted_patient_hides_encounters(client: TestClient, users_db: Engine) -> None:
    with Session(users_db) as s, s.begin():
        add_encounter(s, 1, 500, admission=date(2005, 1, 1))
        add_encounter(s, 2, 500, admission=date(2005, 2, 1))
        add_encounter(s, 3, 501, admission=date(2005, 3, 1))
    h = auth_header(client, "ops")
    r = client.get("/patients/500/encounters", headers=h)
    assert r.status_code == 200 and r.json()["total"] == 2
    assert [e["encounter_id"] for e in r.json()["items"]] == [2, 1]  # newest admission first
    assert client.get("/patients/999/encounters", headers=h).status_code == 404
    client.delete("/patients/500", headers=auth_header(client, "admin"))
    assert client.get("/encounters/1", headers=h).status_code == 404  # encounter of a deleted patient is invisible
    with users_db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM v_active_encounters WHERE patient_nbr = 500")).scalar_one() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM v_active_encounters")).scalar_one() == 1


def test_patient_update_audit_has_before_and_after(client: TestClient, users_db: Engine) -> None:
    import json
    h = auth_header(client, "ops")
    client.post("/patients", json=BODY, headers=h)
    client.put("/patients/900000001", json={"gender": "Unknown"}, headers=h)
    action, entity_id, username, role, before, after = audit_rows(users_db)[1]
    before, after = (json.loads(x) if isinstance(x, str) else x for x in (before, after))
    assert (action, entity_id, username, role) == ("UPDATE", "900000001", "ops", "clinical_ops")
    # the trail says WHAT changed, never the sensitive values themselves
    assert after["changed_fields"] == ["gender"] and before["gender_recorded"] and after["gender_recorded"]
    assert "Female" not in str((before, after)) and "Unknown" not in str((before, after)) and "Caucasian" not in str((before, after))
    assert "race" not in before and "gender" not in before
