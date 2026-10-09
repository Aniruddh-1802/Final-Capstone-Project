"""Filtering, sorting, pagination, search, date ranges, admin lists and reference lookups (L10)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from etl.pipeline import run_pipeline
from tests.api.conftest import PASSWORDS, auth_header, login

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mini_diabetic.csv"
SORTS = ["encounter_id", "admission_date", "time_in_hospital", "num_medications", "number_inpatient", "age_order"]


@pytest.fixture()
def loaded(client: TestClient, users_db: Engine, tmp_path: Path) -> TestClient:
    assert run_pipeline(FIXTURE, engine=users_db, rejected_dir=tmp_path).status == "SUCCESS"
    return client


@pytest.fixture(scope="module")
def oracle() -> pd.DataFrame:
    """The fixture as pandas: an implementation independent of the SQL under test."""
    df = pd.read_csv(FIXTURE, keep_default_na=False, na_values=["?", ""], dtype={"diag_1": str, "diag_2": str, "diag_3": str})
    df["admission_date"] = pd.to_datetime(df["admission_date"]).dt.date
    return df


def ids(response) -> list[int]:
    assert response.status_code == 200, response.text
    return [i["encounter_id"] for i in response.json()["items"]]


def listing(client: TestClient, user: str = "admin", **params):
    return client.get("/encounters", params={"page_size": 100, **params}, headers=auth_header(client, user))


def expect(oracle: pd.DataFrame, mask: pd.Series) -> list[int]:
    return sorted(oracle.loc[mask, "encounter_id"])


# ---- each filter alone and combined ---------------------------------------------------------------------------
@pytest.mark.parametrize("params, mask", [
    ({"date_from": "2005-01-10"}, lambda d: d.admission_date >= date(2005, 1, 10)),
    ({"date_to": "2005-01-10"}, lambda d: d.admission_date <= date(2005, 1, 10)),
    ({"date_from": "2005-01-04", "date_to": "2005-01-13"}, lambda d: d.admission_date.between(date(2005, 1, 4), date(2005, 1, 13))),
    ({"age_group": "[70-80)"}, lambda d: d.age == "[70-80)"),
    ({"admission_type_id": 4}, lambda d: d.admission_type_id == 4),
    ({"admission_source_id": 4}, lambda d: d.admission_source_id == 4),
    ({"discharge_disposition_id": 11}, lambda d: d.discharge_disposition_id == 11),
    ({"specialty": "Cardiology"}, lambda d: d.medical_specialty == "Cardiology"),
    ({"readmitted": "<30"}, lambda d: d.readmitted == "<30"),
    ({"readmitted": ">30"}, lambda d: d.readmitted == ">30"),
    ({"readmitted": "NO"}, lambda d: d.readmitted == "NO"),
    ({"min_los": 7}, lambda d: d.time_in_hospital >= 7),
    ({"max_los": 2}, lambda d: d.time_in_hospital <= 2),
    ({"min_los": 2, "max_los": 3}, lambda d: d.time_in_hospital.between(2, 3)),
    ({"patient_nbr": 1001}, lambda d: d.patient_nbr == 1001),
    ({"age_group": "[70-80)", "readmitted": "<30"}, lambda d: (d.age == "[70-80)") & (d.readmitted == "<30")),
    ({"date_from": "2005-01-10", "readmitted": "<30", "min_los": 2},
     lambda d: (d.admission_date >= date(2005, 1, 10)) & (d.readmitted == "<30") & (d.time_in_hospital >= 2)),
    ({"specialty": "Cardiology", "max_los": 5}, lambda d: (d.medical_specialty == "Cardiology") & (d.time_in_hospital <= 5)),
])
def test_filters_match_the_pandas_oracle(loaded: TestClient, oracle: pd.DataFrame, params: dict, mask) -> None:
    r = listing(loaded, sort_by="encounter_id", sort_dir="asc", **params)
    assert ids(r) == expect(oracle, mask(oracle))
    assert r.json()["total"] == len(expect(oracle, mask(oracle)))
    assert set(r.json()["meta"]["filters"]) == set(params)  # the server reports exactly the filters it applied


def test_date_boundaries_are_inclusive_on_both_ends(loaded: TestClient) -> None:
    # encounter 2 was admitted 2005-01-04, encounter 3 on 2005-01-07
    assert ids(listing(loaded, date_from="2005-01-04", date_to="2005-01-04")) == [2]
    assert sorted(ids(listing(loaded, date_from="2005-01-04", date_to="2005-01-07"))) == [2, 3]
    assert ids(listing(loaded, date_from="2005-01-05", date_to="2005-01-06")) == []


@pytest.mark.parametrize("q, expected", [
    ("17", [17]), ("1001", [1, 2, 3]), ("V57", [19]), ("v57", [19]), ("250.8", [19]), ("E9", [19]), ("V", [19, 20]),
    ("V45", [20]), ("038", []), ("E878.1", [21]), ("zzz", []),
])
def test_search_semantics(loaded: TestClient, q: str, expected: list[int]) -> None:
    assert sorted(ids(listing(loaded, q=q))) == expected


def test_numeric_q_is_an_id_not_an_icd_prefix(loaded: TestClient) -> None:
    assert ids(listing(loaded, q="250")) == []  # documented: digits only means an id; write 250. for the ICD prefix
    assert 19 in ids(listing(loaded, q="250.")) and 1 in ids(listing(loaded, q="250."))


@pytest.mark.parametrize("q", ["%", "25_", "a b", "x" * 12, "1' OR '1'='1", "250;DROP"])
def test_unsafe_search_text_is_rejected_not_executed(loaded: TestClient, q: str) -> None:
    r = loaded.get("/encounters", params={"q": q}, headers=auth_header(loaded, "admin"))
    assert r.status_code == 422
    assert listing(loaded).json()["total"] == 30  # nothing was damaged


def test_total_matches_a_direct_sql_count(loaded: TestClient, users_db: Engine) -> None:
    r = listing(loaded, age_group="[70-80)", readmitted="NO")
    with users_db.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM v_active_encounters WHERE age_group = '[70-80)' AND readmitted = 'NO'")).scalar_one()
    assert r.json()["total"] == n == len(r.json()["items"])


# ---- sorting and stable paging --------------------------------------------------------------------------------
@pytest.mark.parametrize("sort_by", SORTS)
@pytest.mark.parametrize("sort_dir", ["asc", "desc"])
def test_paging_walks_every_row_once_in_the_requested_order(loaded: TestClient, oracle: pd.DataFrame, sort_by: str, sort_dir: str) -> None:
    key = {"age_order": "age", "admission_date": "admission_date"}.get(sort_by, sort_by)
    work = oracle.assign(age=oracle["age"].map({f"[{i}-{i + 10})": n for n, i in enumerate(range(0, 100, 10), 1)}))
    expected = work.sort_values([key, "encounter_id"], ascending=sort_dir == "asc").encounter_id.tolist()
    seen: list[int] = []
    page = 1
    while True:
        r = loaded.get("/encounters", params={"page": page, "page_size": 7, "sort_by": sort_by, "sort_dir": sort_dir},
                       headers=auth_header(loaded, "admin"))
        body = r.json()
        seen += [i["encounter_id"] for i in body["items"]]
        if page >= body["pages"]:
            break
        page += 1
    assert body["pages"] == 5 and body["total"] == 30
    assert len(seen) == len(set(seen)) == 30  # no repeats, no gaps (heavy ties in time_in_hospital / number_inpatient)
    assert seen == expected


def test_page_past_the_end_is_empty_with_correct_total(loaded: TestClient) -> None:
    r = loaded.get("/encounters", params={"page": 99, "page_size": 7}, headers=auth_header(loaded, "admin"))
    assert r.status_code == 200
    assert r.json()["items"] == [] and r.json()["total"] == 30 and r.json()["pages"] == 5 and r.json()["page"] == 99


@pytest.mark.parametrize("params", [
    {"page_size": 101}, {"page_size": 0}, {"page": 0}, {"page": -1}, {"page_size": "abc"},
    {"sort_by": "password_hash"}, {"sort_by": "encounter_id;DROP TABLE x"}, {"sort_by": "encounter_id DESC, (SELECT 1)"},
    {"sort_by": "patient_nbr"}, {"sort_dir": "sideways"}, {"readmitted": "MAYBE"}, {"age_group": "old"},
    {"min_los": 0}, {"max_los": 15}, {"min_los": 5, "max_los": 2}, {"date_from": "2005-02-01", "date_to": "2005-01-01"},
    {"date_from": "not-a-date"}, {"admission_type_id": 0},
])
def test_invalid_parameters_are_422_with_the_error_contract(loaded: TestClient, params: dict) -> None:
    r = loaded.get("/encounters", params=params, headers=auth_header(loaded, "admin"))
    assert r.status_code == 422 and set(r.json()["error"]) == {"code", "message", "details"}
    assert r.json()["error"]["details"]
    assert listing(loaded).json()["total"] == 30


def test_default_envelope_and_meta(loaded: TestClient) -> None:
    r = loaded.get("/encounters", headers=auth_header(loaded, "admin")).json()
    assert {"items", "total", "page", "page_size", "pages", "meta"} == set(r)
    assert (r["page"], r["page_size"], r["total"], r["pages"]) == (1, 25, 30, 2) and len(r["items"]) == 25
    assert r["meta"]["sort_by"] == "admission_date" and r["meta"]["sort_dir"] == "desc" and r["meta"]["dates_simulated"] is True
    dates = [i["admission_date"] for i in r["items"]]
    assert dates == sorted(dates, reverse=True)
    f = loaded.get("/encounters", params={"readmitted": "<30", "min_los": 2}, headers=auth_header(loaded, "admin")).json()
    assert f["meta"]["filters"] == {"readmitted": "<30", "min_los": 2}


def test_analyst_listing_is_minimised(loaded: TestClient) -> None:
    r = listing(loaded, "ana")
    assert r.status_code == 200 and r.json()["total"] == 30
    for item in r.json()["items"]:
        assert "patient_nbr" not in item and "source_batch_id" not in item and "race" not in item
    assert listing(loaded, "ana", patient_nbr=1001).status_code == 403
    assert ids(listing(loaded, "ana", q="1001")) == []  # numeric q can only match encounter_id for analysts
    assert ids(listing(loaded, "ana", q="17")) == [17]


# ---- patients list ---------------------------------------------------------------------------------------------
def test_patient_list_filters_sorting_and_roles(loaded: TestClient) -> None:
    ops = auth_header(loaded, "ops")
    r = loaded.get("/patients", params={"page_size": 100}, headers=ops).json()
    assert r["total"] == 28 and [p["patient_nbr"] for p in r["items"]] == sorted(p["patient_nbr"] for p in r["items"])
    assert next(p for p in r["items"] if p["patient_nbr"] == 1001)["encounter_count"] == 3
    multi = loaded.get("/patients", params={"has_multiple_encounters": True}, headers=ops).json()
    assert [p["patient_nbr"] for p in multi["items"]] == [1001] and multi["total"] == 1
    assert loaded.get("/patients", params={"has_multiple_encounters": False}, headers=ops).json()["total"] == 27
    assert [p["patient_nbr"] for p in loaded.get("/patients", params={"q": 1010}, headers=ops).json()["items"]] == [1010]
    desc = loaded.get("/patients", params={"sort_by": "patient_nbr", "sort_dir": "desc", "page_size": 3}, headers=ops).json()
    assert [p["patient_nbr"] for p in desc["items"]] == [1028, 1027, 1026]
    assert loaded.get("/patients", params={"sort_by": "race"}, headers=ops).status_code == 422
    assert loaded.get("/patients", headers=auth_header(loaded, "ana")).status_code == 403


# ---- admin endpoints --------------------------------------------------------------------------------------------
def test_admin_endpoints_follow_the_permission_matrix(loaded: TestClient) -> None:
    admin, ops, ana = (auth_header(loaded, n) for n in ("admin", "ops", "ana"))
    table = {"/admin/audit-logs": (200, 403, 403), "/admin/users": (200, 403, 403),
             "/admin/pipeline-runs": (200, 200, 403), "/admin/dq-issues": (200, 200, 403)}
    for url, (a, o, n) in table.items():
        assert [loaded.get(url, headers=h).status_code for h in (admin, ops, ana)] == [a, o, n], url
        assert loaded.get(url).status_code == 401


def test_users_never_expose_password_hash_and_new_users_can_log_in(loaded: TestClient) -> None:
    admin = auth_header(loaded, "admin")
    body = loaded.get("/admin/users", headers=admin)
    assert "password" not in body.text.lower() and "$2b$" not in body.text
    assert {u["username"] for u in body.json()["items"]} >= {"admin", "ops", "ana", "inactive"}
    new = {"username": "created.user", "password": "a-long-passphrase-123", "role": "clinical_ops"}
    r = loaded.post("/admin/users", json=new, headers=admin)
    assert r.status_code == 201 and r.json()["role"] == "clinical_ops" and "password" not in r.text.lower()
    assert login(loaded, "created.user", "a-long-passphrase-123").status_code == 200
    assert loaded.post("/admin/users", json=new, headers=admin).status_code == 409
    for bad in ({**new, "username": "x"}, {**new, "username": "a b"}, {**new, "username": "ok.name", "password": "short"},
                {**new, "username": "ok.name", "role": "root"}, {**new, "username": "ok.name", "password": "x" * 73}):
        assert loaded.post("/admin/users", json=bad, headers=admin).status_code == 422
    assert loaded.post("/admin/users", json=new, headers=auth_header(loaded, "ops")).status_code == 403


def test_pipeline_runs_and_dq_issue_filters(loaded: TestClient) -> None:
    ops = auth_header(loaded, "ops")
    runs = loaded.get("/admin/pipeline-runs", headers=ops).json()
    assert runs["total"] == 1 and runs["items"][0]["status"] == "SUCCESS" and runs["items"][0]["rows_loaded"] == 30
    assert loaded.get("/admin/pipeline-runs", params={"status": "FAILED"}, headers=ops).json()["total"] == 0
    today = date.today().isoformat()
    assert loaded.get("/admin/pipeline-runs", params={"date_from": today, "date_to": today}, headers=ops).json()["total"] == 1
    assert loaded.get("/admin/pipeline-runs", params={"date_from": "2030-01-01"}, headers=ops).json()["total"] == 0
    assert loaded.get("/admin/pipeline-runs", params={"date_from": today, "date_to": "2000-01-01"}, headers=ops).status_code == 422
    assert loaded.get("/admin/pipeline-runs", params={"status": "BROKEN"}, headers=ops).status_code == 422
    run_id = runs["items"][0]["run_id"]
    dq = loaded.get("/admin/dq-issues", params={"run_id": run_id, "rule_name": "DQ11", "page_size": 100}, headers=ops).json()
    assert dq["total"] > 0 and all(i["rule_name"] == "DQ11" and i["action"] == "metric" for i in dq["items"])
    assert loaded.get("/admin/dq-issues", params={"run_id": 9999}, headers=ops).json()["total"] == 0
    assert loaded.get("/admin/dq-issues", params={"severity": "info", "run_id": run_id}, headers=ops).json()["total"] >= dq["total"]


def test_audit_log_filters_and_inclusive_day_range(loaded: TestClient) -> None:
    admin, ops = auth_header(loaded, "admin"), auth_header(loaded, "ops")
    loaded.post("/patients", json={"patient_nbr": 777, "race": "Asian", "gender": "Male"}, headers=ops)
    loaded.put("/patients/777", json={"gender": "Female"}, headers=ops)
    loaded.delete("/patients/777", headers=admin)
    get = lambda **p: loaded.get("/admin/audit-logs", params=p, headers=admin).json()  # noqa: E731
    assert get()["total"] == 3
    assert [r["action"] for r in get(sort_dir="asc")["items"]] == ["CREATE", "UPDATE", "DELETE"]
    assert get(action="UPDATE")["total"] == 1 and get(user="ops")["total"] == 2 and get(user="admin")["total"] == 1
    assert get(entity_type="patient", entity_id="777")["total"] == 3 and get(entity_id="778")["total"] == 0
    today = date.today().isoformat()
    assert get(date_from=today, date_to=today)["total"] == 3  # the whole of today is included
    assert get(date_from="2999-01-01")["total"] == 0
    assert loaded.get("/admin/audit-logs", params={"action": "HACK"}, headers=admin).status_code == 422
    first = get(sort_dir="asc")["items"][0]
    assert first["before_json"] is None and first["after_json"]["patient_nbr"] == 777 and "password" not in str(first).lower()


# ---- reference lookups -------------------------------------------------------------------------------------------
def test_reference_lookups_for_every_role(loaded: TestClient) -> None:
    for user in ("admin", "ops", "ana"):
        h = auth_header(loaded, user)
        types = loaded.get("/reference/admission-types", headers=h).json()
        assert len(types) == 8 and types[0] == {"id": 1, "label": "Emergency"}
        assert len(loaded.get("/reference/admission-sources", headers=h).json()) == 25
    h = auth_header(loaded, "ana")
    ages = loaded.get("/reference/age-groups", headers=h).json()
    assert [a["label"] for a in ages][:2] == ["[0-10)", "[10-20)"] and ages[-1] == {"id": 10, "label": "[90-100)"}
    dispositions = loaded.get("/reference/discharge-dispositions", headers=h).json()
    assert sorted(d["id"] for d in dispositions if d["is_expired_or_hospice"]) == [11, 13, 14, 19, 20, 21]
    specialties = loaded.get("/reference/specialties", headers=h).json()
    assert {"Cardiology", "InternalMedicine"} <= {s["label"] for s in specialties}
    assert loaded.get("/reference/age-groups").status_code == 401
