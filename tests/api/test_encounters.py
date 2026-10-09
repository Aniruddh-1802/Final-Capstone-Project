"""Encounter CRUD: validation, server-derived flags, role minimisation, soft delete."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.api.conftest import auth_header
from tests.api.helpers import add_encounter, valid_payload

URL = "/encounters"


@pytest.fixture()
def with_patient(client: TestClient) -> dict:
    h = auth_header(client, "admin")
    assert client.post("/patients", json={"patient_nbr": 900000001, "race": "Asian", "gender": "Male"}, headers=h).status_code == 201
    return h


def errors(r) -> dict[str, str]:
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    return {d["loc"][-1]: d["msg"] for d in r.json()["error"]["details"]}


def stored(db: Engine, encounter_id: int = 900000001) -> dict:
    with db.connect() as conn:
        row = conn.execute(text("SELECT o.readmitted, o.readmitted_30d, o.any_readmission, o.is_readmission_eligible, "
                                "e.age_order, e.is_deleted FROM encounters e JOIN encounter_outcomes o USING (encounter_id) "
                                "WHERE e.encounter_id = :i"), {"i": encounter_id}).one_or_none()
    return dict(row._mapping) if row else {}


def test_create_returns_full_record_with_children_and_derived_fields(client: TestClient, with_patient: dict) -> None:
    r = client.post(URL, json=valid_payload(), headers=with_patient)
    assert r.status_code == 201
    body = r.json()
    assert body["encounter_id"] == 900000001 and body["patient_nbr"] == 900000001 and body["age_order"] == 8
    assert body["admission_type"] == "Emergency" and body["medical_specialty"] == "Cardiology" and body["payer_code"] == "MC"
    assert body["readmitted_30d"] is False and body["is_readmission_eligible"] is True
    assert body["diagnoses"] == [{"position": 1, "icd9_code": "250.83"}, {"position": 2, "icd9_code": "401.9"}]
    assert body["medications"] == [{"drug_name": "insulin", "dosage_status": "Steady"}]
    assert body["dates_simulated"] is True
    assert "race" not in body and "gender" not in body  # demographics never ride on encounters


def test_client_supplied_derived_flags_are_ignored(client: TestClient, with_patient: dict, users_db: Engine) -> None:
    payload = valid_payload(readmitted="NO", readmitted_30d=True, any_readmission=True, is_readmission_eligible=False,
                            age_order=1)
    assert client.post(URL, json=payload, headers=with_patient).status_code == 201
    row = stored(users_db)
    assert row["readmitted_30d"] == 0 and row["any_readmission"] == 0 and row["is_readmission_eligible"] == 1
    assert row["age_order"] == 8  # derived from age_group, not from the client


def test_expired_disposition_makes_encounter_ineligible_and_30d_flag_follows_readmitted(
        client: TestClient, with_patient: dict, users_db: Engine) -> None:
    client.post(URL, json=valid_payload(encounter_id=1, discharge_disposition_id=11, readmitted="<30"), headers=with_patient)
    row = stored(users_db, 1)
    assert (row["readmitted_30d"], row["any_readmission"], row["is_readmission_eligible"]) == (1, 1, 0)


def test_duplicate_encounter_is_409(client: TestClient, with_patient: dict) -> None:
    assert client.post(URL, json=valid_payload(), headers=with_patient).status_code == 201
    r = client.post(URL, json=valid_payload(), headers=with_patient)
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"


@pytest.mark.parametrize("override, field", [
    ({"time_in_hospital": 0}, "time_in_hospital"), ({"time_in_hospital": 15}, "time_in_hospital"),
    ({"age_group": "[5-15)"}, "age_group"), ({"num_medications": -1}, "num_medications"),
    ({"number_emergency": 100000}, "number_emergency"), ({"readmitted": "MAYBE"}, "readmitted"),
    ({"max_glu_serum": "high"}, "max_glu_serum"), ({"encounter_id": 0}, "encounter_id"),
    ({"diagnoses": [{"position": 1, "icd9_code": "ABC"}]}, "icd9_code"),
    ({"diagnoses": [{"position": 4, "icd9_code": "250"}]}, "position"),
    ({"diagnoses": [{"position": 1, "icd9_code": "250"}] * 4}, "diagnoses"),
    ({"medications": [{"drug_name": "aspirin", "dosage_status": "Steady"}]}, "drug_name"),
    ({"medications": [{"drug_name": "insulin", "dosage_status": "No"}]}, "dosage_status"),
])
def test_field_level_validation(client: TestClient, with_patient: dict, override: dict, field: str) -> None:
    assert field in errors(client.post(URL, json=valid_payload(**override), headers=with_patient))


def test_date_rules(client: TestClient, with_patient: dict) -> None:
    e = errors(client.post(URL, json=valid_payload(discharge_date="2005-02-27"), headers=with_patient))
    assert "discharge_date" in e and "before" in e["discharge_date"].lower()
    e = errors(client.post(URL, json=valid_payload(discharge_date="2005-03-10"), headers=with_patient))
    assert "time_in_hospital" in e["discharge_date"]  # six days apart but LOS says three
    e = errors(client.post(URL, json=valid_payload(admission_date="2015-03-01", discharge_date="2015-03-04"), headers=with_patient))
    assert "study window" in e["admission_date"]
    assert client.post(URL, json=valid_payload(admission_date="2005-02-30"), headers=with_patient).status_code == 422


def test_unknown_references_are_field_level_422s(client: TestClient, with_patient: dict) -> None:
    e = errors(client.post(URL, json=valid_payload(admission_type_id=99, discharge_disposition_id=99,
                                                  admission_source_id=99, patient_nbr=123), headers=with_patient))
    assert {"admission_type_id", "discharge_disposition_id", "admission_source_id", "patient_nbr"} <= set(e)


def test_missing_required_fields_list_every_field(client: TestClient, with_patient: dict) -> None:
    e = errors(client.post(URL, json={"encounter_id": 5}, headers=with_patient))
    assert {"patient_nbr", "admission_date", "readmitted", "time_in_hospital"} <= set(e)


def test_get_one_by_role_minimisation(client: TestClient, with_patient: dict) -> None:
    client.post(URL, json=valid_payload(), headers=with_patient)
    for user in ("admin", "ops"):
        body = client.get(f"{URL}/900000001", headers=auth_header(client, user)).json()
        assert body["patient_nbr"] == 900000001 and "source_batch_id" in body
    ana = client.get(f"{URL}/900000001", headers=auth_header(client, "ana"))
    assert ana.status_code == 200
    assert "patient_nbr" not in ana.json() and "source_batch_id" not in ana.json()
    assert "race" not in ana.text and "gender" not in ana.text
    assert ana.json()["time_in_hospital"] == 3  # clinical fields are still there


def test_analyst_is_read_only(client: TestClient, with_patient: dict) -> None:
    client.post(URL, json=valid_payload(), headers=with_patient)
    ana = auth_header(client, "ana")
    assert client.post(URL, json=valid_payload(encounter_id=2), headers=ana).status_code == 403
    assert client.put(f"{URL}/900000001", json={"readmitted": "<30"}, headers=ana).status_code == 403
    assert client.delete(f"{URL}/900000001", headers=ana).status_code == 403


def test_update_is_partial_rederives_flags_and_revalidates_merged_state(client: TestClient, with_patient: dict, users_db: Engine) -> None:
    client.post(URL, json=valid_payload(), headers=with_patient)
    ops = auth_header(client, "ops")
    r = client.put(f"{URL}/900000001", json={"readmitted": "<30", "number_inpatient": 2}, headers=ops)
    assert r.status_code == 200 and r.json()["readmitted_30d"] is True and r.json()["number_inpatient"] == 2
    assert r.json()["num_medications"] == 12  # untouched
    r = client.put(f"{URL}/900000001", json={"discharge_disposition_id": 13}, headers=ops)
    assert r.json()["is_readmission_eligible"] is False and r.json()["readmitted_30d"] is True
    # changing only the stay length breaks the date arithmetic of the stored dates -> rejected, nothing changes
    e = errors(client.put(f"{URL}/900000001", json={"time_in_hospital": 5}, headers=ops))
    assert "discharge_date" in e
    assert client.get(f"{URL}/900000001", headers=ops).json()["time_in_hospital"] == 3
    r = client.put(f"{URL}/900000001", json={"time_in_hospital": 5, "discharge_date": "2005-03-06"}, headers=ops)
    assert r.status_code == 200 and r.json()["time_in_hospital"] == 5


def test_update_replaces_children_and_specialty(client: TestClient, with_patient: dict) -> None:
    client.post(URL, json=valid_payload(), headers=with_patient)
    ops = auth_header(client, "ops")
    r = client.put(f"{URL}/900000001", json={"diagnoses": [{"position": 1, "icd9_code": "V57"}],
                                             "medications": [], "medical_specialty": "Nephrology", "payer_code": None},
                   headers=ops)
    body = r.json()
    assert body["diagnoses"] == [{"position": 1, "icd9_code": "V57"}] and body["medications"] == []
    assert body["medical_specialty"] == "Nephrology" and body["payer_code"] is None


@pytest.mark.parametrize("body", [{}, {"time_in_hospital": None}, {"readmitted": None}, {"age_group": "[1-2)"},
                                  {"diagnoses": [{"position": 1, "icd9_code": "250"}, {"position": 1, "icd9_code": "401"}]}])
def test_invalid_updates_are_422(client: TestClient, with_patient: dict, body: dict) -> None:
    client.post(URL, json=valid_payload(), headers=with_patient)
    assert client.put(f"{URL}/900000001", json=body, headers=auth_header(client, "ops")).status_code == 422


def test_unknown_encounter_is_404_for_get_put_delete(client: TestClient) -> None:
    h = auth_header(client, "admin")
    assert client.get(f"{URL}/42", headers=h).status_code == 404
    assert client.put(f"{URL}/42", json={"readmitted": "NO"}, headers=h).status_code == 404
    assert client.delete(f"{URL}/42", headers=h).status_code == 404


def test_delete_is_admin_only_soft_and_invisible_everywhere(client: TestClient, with_patient: dict, users_db: Engine) -> None:
    client.post(URL, json=valid_payload(), headers=with_patient)
    with Session(users_db) as s, s.begin():
        add_encounter(s, 7, 7, admission=date(2005, 6, 1))

    def active() -> int:
        with users_db.connect() as conn:
            return conn.execute(text("SELECT total_encounters FROM (SELECT COUNT(*) AS total_encounters "
                                     "FROM v_active_encounters) t")).scalar_one()
    before = active()
    assert client.delete(f"{URL}/900000001", headers=auth_header(client, "ops")).status_code == 403
    assert client.delete(f"{URL}/900000001", headers=auth_header(client, "ana")).status_code == 403
    assert active() == before
    assert client.delete(f"{URL}/900000001", headers=auth_header(client, "admin")).status_code == 204
    assert active() == before - 1  # exactly one fewer in the view the analytics read
    h = auth_header(client, "ops")
    assert client.get(f"{URL}/900000001", headers=h).status_code == 404
    assert 900000001 not in [e["encounter_id"] for e in client.get(URL, headers=h).json()["items"]]
    assert client.delete(f"{URL}/900000001", headers=auth_header(client, "admin")).status_code == 404
    assert client.put(f"{URL}/900000001", json={"readmitted": "NO"}, headers=h).status_code == 404
    assert stored(users_db)["is_deleted"] == 1  # soft: the row is still there
