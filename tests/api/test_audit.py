"""Audit trail: one row per change, correct before/after and user, same transaction as the data, no secrets."""
from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.services import audit
from tests.api.conftest import auth_header
from tests.api.helpers import valid_payload

ENC = 900000001


def rows(db: Engine, entity_type: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM audit_logs" + (" WHERE entity_type = :t" if entity_type else "") + " ORDER BY id"
    with db.connect() as conn:
        out = [dict(r._mapping) for r in conn.execute(text(sql), {"t": entity_type} if entity_type else {})]
    for r in out:
        for k in ("before_json", "after_json"):
            if isinstance(r[k], str):
                r[k] = json.loads(r[k])
    return out


def count(db: Engine, table: str, where: str = "1=1") -> int:
    with db.connect() as conn:
        return conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {where}")).scalar_one()


@pytest.fixture()
def seeded(client: TestClient) -> dict:
    h = auth_header(client, "admin")
    client.post("/patients", json={"patient_nbr": ENC, "race": "Asian", "gender": "Male"}, headers=h)
    return h


def changed_keys(before: dict, after: dict) -> set[str]:
    return {k for k in set(before) | set(after) if before.get(k) != after.get(k)}


def test_create_update_delete_each_write_exactly_one_audit_row(client: TestClient, seeded: dict, users_db: Engine) -> None:
    ops, admin = auth_header(client, "ops"), auth_header(client, "admin")
    r = client.post("/encounters", json=valid_payload(), headers=ops)
    request_id = r.headers["x-request-id"]
    client.put(f"/encounters/{ENC}", json={"readmitted": "<30", "number_inpatient": 2}, headers=ops)
    client.delete(f"/encounters/{ENC}", headers=admin)
    enc = rows(users_db, "encounter")
    assert [a["action"] for a in enc] == ["CREATE", "UPDATE", "DELETE"] and {a["entity_id"] for a in enc} == {str(ENC)}

    create, update, delete = enc
    assert create["before_json"] is None and create["after_json"]["readmitted"] == "NO"
    assert create["after_json"]["diagnoses"][0] == {"position": 1, "icd9_code": "250.83"}
    assert create["after_json"]["medications"] == [{"drug_name": "insulin", "dosage_status": "Steady"}]
    # the update row differs ONLY in what changed (plus the flags derived from readmitted)
    assert changed_keys(update["before_json"], update["after_json"]) == {
        "readmitted", "readmitted_30d", "any_readmission", "number_inpatient"}
    assert update["before_json"]["number_inpatient"] == 0 and update["after_json"]["number_inpatient"] == 2
    assert changed_keys(delete["before_json"], delete["after_json"]) == {"is_deleted"}
    assert delete["before_json"]["is_deleted"] is False and delete["after_json"]["is_deleted"] is True

    # who / role / where / which request
    assert (create["username"], create["role"], create["user_id"] is not None) == ("ops", "clinical_ops", True)
    assert (delete["username"], delete["role"]) == ("admin", "administrator")
    assert create["request_id"] == request_id and create["ip_address"]


def test_a_read_or_rejected_request_writes_no_audit_row(client: TestClient, seeded: dict, users_db: Engine) -> None:
    before = count(users_db, "audit_logs")
    ops = auth_header(client, "ops")
    client.get("/patients", headers=ops)
    client.post("/encounters", json=valid_payload(time_in_hospital=0), headers=ops)  # 422
    client.post("/encounters", json=valid_payload(), headers=auth_header(client, "ana"))  # 403
    client.put("/encounters/42", json={"readmitted": "NO"}, headers=ops)  # 404
    assert count(users_db, "audit_logs") == before


def test_audit_failure_rolls_back_the_data_change_on_create(client: TestClient, seeded: dict, users_db: Engine,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("audit write failed")
    monkeypatch.setattr(audit, "record", boom)
    r = client.post("/encounters", json=valid_payload(), headers=auth_header(client, "ops"))
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal_error"
    assert count(users_db, "encounters", f"encounter_id = {ENC}") == 0  # no change without its trail
    assert count(users_db, "encounter_outcomes") == 0 and count(users_db, "encounter_diagnoses") == 0
    assert count(users_db, "audit_logs", "entity_type = 'encounter'") == 0


def test_audit_failure_rolls_back_update_and_delete(client: TestClient, seeded: dict, users_db: Engine,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    ops, admin = auth_header(client, "ops"), auth_header(client, "admin")
    client.post("/encounters", json=valid_payload(), headers=ops)
    baseline = count(users_db, "audit_logs")
    monkeypatch.setattr(audit, "record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("audit write failed")))
    assert client.put(f"/encounters/{ENC}", json={"readmitted": "<30", "number_inpatient": 4}, headers=ops).status_code == 500
    assert client.delete(f"/encounters/{ENC}", headers=admin).status_code == 500
    monkeypatch.undo()
    detail = client.get(f"/encounters/{ENC}", headers=ops).json()
    assert detail["readmitted"] == "NO" and detail["number_inpatient"] == 0  # update did not stick
    assert count(users_db, "encounters", f"encounter_id = {ENC} AND is_deleted = 0") == 1  # nor did the delete
    assert count(users_db, "audit_logs") == baseline


def test_commit_failure_leaves_neither_data_nor_audit_row(client: TestClient, seeded: dict, users_db: Engine,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = count(users_db, "audit_logs")
    ops = auth_header(client, "ops")  # log in first: login itself commits (last_login_at)

    def failing_commit(self: Session) -> None:
        raise RuntimeError("commit failed")
    monkeypatch.setattr(Session, "commit", failing_commit)
    assert client.post("/encounters", json=valid_payload(), headers=ops).status_code == 500
    monkeypatch.undo()
    assert count(users_db, "encounters") == 0 and count(users_db, "audit_logs") == baseline


def test_patient_and_user_changes_are_audited_too(client: TestClient, seeded: dict, users_db: Engine) -> None:
    admin = auth_header(client, "admin")
    r = client.post("/admin/users", json={"username": "new.user", "password": "a-long-passphrase-123", "role": "analyst"},
                    headers=admin)
    assert r.status_code == 201
    assert [a["action"] for a in rows(users_db, "patient")] == ["CREATE"]
    user_row = rows(users_db, "user")[0]
    assert user_row["after_json"] == {"username": "new.user", "role": "analyst", "is_active": True}


def test_no_secret_ever_reaches_the_audit_table_or_response(client: TestClient, seeded: dict, users_db: Engine) -> None:
    admin = auth_header(client, "admin")
    client.post("/admin/users", json={"username": "secret.test", "password": "super-secret-pass-999", "role": "analyst"},
                headers=admin)
    with users_db.connect() as conn:
        dump = " ".join(str(v) for r in conn.execute(text("SELECT * FROM audit_logs")) for v in r)
    assert "super-secret-pass-999" not in dump and "$2b$" not in dump and "password" not in dump.lower()
    listing = client.get("/admin/audit-logs", headers=admin).text
    assert "super-secret-pass-999" not in listing and "$2b$" not in listing and "Bearer" not in listing


def test_scrub_removes_secret_keys_and_serialises_dates() -> None:
    from datetime import date
    out = audit.scrub({"name": "x", "password": "p", "nested": {"password_hash": "h", "token": "t", "ok": 1},
                       "d": date(2005, 1, 2), "list": [{"access_token": "a", "v": 2}]})
    assert out == {"name": "x", "nested": {"ok": 1}, "d": "2005-01-02", "list": [{"v": 2}]}
    assert audit.scrub(None) is None
