"""Analytics endpoints on a 40-row fixture whose expected numbers are worked out by hand (see HAND CALCULATIONS)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.services.kpi_sql import load_named_queries, run_query
from tests.api.conftest import auth_header
from tests.api.helpers import admission_of, load_forty

# HAND CALCULATIONS -------------------------------------------------------------------------------------------
# Encounters 1..40; id 40 is SOFT-DELETED, so 39 are active.
#   age_group : ids 1-10 [50-60) | 11-25 [70-80) | 26-40 [80-90)         -> active 10 / 15 / 14
#   disposition: 11 for id 5, 13 for id 12, 14 for id 30 (expired/hospice -> NOT eligible), 1 otherwise -> 36 eligible
#   readmitted: '<30' ids {2,3,5,12,13,14,28,40}; '>30' ids {1,4,20,21}; else NO
#     eligible & active '<30' = {2,3,13,14,28} = 5      (5 and 12 are ineligible, 40 is deleted)
#     eligible & active any   = 5 + 4 = 9
#   30-day rate = 5/36 = 0.138889 (over all 39 it would be 0.128205); any rate = 9/36 = 0.25
#   length of stay = (id % 5) + 1; sum over ids 1..39 = 119 -> average 119/39 = 3.051282
#   patients: ids 21,22,23 share patient 100, the rest one each -> 37 unique among the 39 active
#   admission type: 1 for ids 1-30 (30 active), 2 for ids 31-40 (9 active)
#   specialty: Cardiology for ids 1-10, none (Unknown) for the rest
#   number_inpatient: id2=1 id3=1 id13=2 id14=3 id28=4, else 0
#   insulin: Steady ids 1,2,3; Up id 13; Down id 28.  metformin Steady ids 1,2.
#   a1c: Norm ids 1,2; >8 id 28; else None
# --------------------------------------------------------------------------------------------------------------
@pytest.fixture()
def api(client: TestClient, users_db: Engine) -> TestClient:
    with Session(users_db) as s, s.begin():
        load_forty(s)
    return client


def get(client: TestClient, url: str, user: str = "ana", **params):
    r = client.get(url, params=params, headers=auth_header(client, user))
    assert r.status_code == 200, r.text
    return r.json()


def by_label(rows: list[dict]) -> dict[str, dict]:
    return {r["label"]: r for r in rows}


# ---- summary ------------------------------------------------------------------------------------------------
def test_summary_matches_hand_calculation(api: TestClient) -> None:
    body = get(api, "/analytics/summary")
    d = body["data"]
    assert d == {"total_encounters": 39, "unique_patients": 37, "avg_length_of_stay": 3.051282,
                 "avg_num_medications": 10.0, "eligible_encounters": 36, "readmitted_30d": 5,
                 "readmission_rate_30d": 0.138889, "any_readmission_rate": 0.25}
    assert d["readmission_rate_30d"] != pytest.approx(5 / 39, abs=1e-3)  # not the all-encounters denominator


def test_every_response_says_dates_are_simulated_and_names_the_denominator(api: TestClient) -> None:
    for url in ("/analytics/summary", "/analytics/admissions-trend", "/analytics/length-of-stay", "/analytics/readmissions",
                "/analytics/medications", "/analytics/utilization"):
        meta = get(api, url)["meta"]
        assert meta["dates_simulated"] is True and "eligible encounters" in meta["denominator"]
        assert meta["generated_at"]
        assert not ({"date_from", "date_to", "age_group", "admission_type_id"} & set(meta["filters"]))  # none were sent


def test_summary_equals_the_l7_headline_sql(api: TestClient, users_db: Engine) -> None:
    api_data = get(api, "/analytics/summary")["data"]
    with users_db.connect() as conn:
        sql = run_query(conn, load_named_queries()["headline"])[0]
    assert api_data["total_encounters"] == sql["total_encounters"] and api_data["unique_patients"] == sql["unique_patients"]
    assert api_data["eligible_encounters"] == sql["eligible_encounters"] and api_data["readmitted_30d"] == sql["readmitted_30d_count"]
    for api_key, sql_key in (("avg_length_of_stay", "avg_length_of_stay"), ("avg_num_medications", "avg_num_medications"),
                             ("readmission_rate_30d", "readmission_rate_30d"), ("any_readmission_rate", "any_readmission_rate")):
        assert api_data[api_key] == pytest.approx(sql[sql_key], abs=1e-6)


def test_summary_filters(api: TestClient) -> None:
    assert get(api, "/analytics/summary", admission_type_id=2)["data"]["total_encounters"] == 9
    assert get(api, "/analytics/summary", age_group="[80-90)")["data"]["total_encounters"] == 14
    first_month = get(api, "/analytics/summary", date_from="2005-01-01", date_to="2005-01-31")
    expected = [i for i in range(1, 40) if date(2005, 1, 1) <= admission_of(i) <= date(2005, 1, 31)]
    assert first_month["data"]["total_encounters"] == len(expected) == 3  # 2005-01-01, 01-16, 01-31 (inclusive end)
    assert first_month["meta"]["filters"] == {"date_from": "2005-01-01", "date_to": "2005-01-31"}
    empty = get(api, "/analytics/summary", date_from="2030-01-01")["data"]
    assert empty["total_encounters"] == 0 and empty["readmission_rate_30d"] is None and empty["avg_length_of_stay"] is None


# ---- grouped endpoints ---------------------------------------------------------------------------------------
def test_readmissions_by_age_group_in_clinical_order_with_small_n(api: TestClient) -> None:
    rows = get(api, "/analytics/readmissions", group_by="age_group")["data"]
    assert [r["label"] for r in rows] == ["[50-60)", "[70-80)", "[80-90)"]
    young, mid, old = rows
    assert (young["encounters"], young["eligible_encounters"], young["readmitted_30d"], young["readmission_rate"]) == (10, 9, 2, 0.222222)
    assert (mid["encounters"], mid["eligible_encounters"], mid["readmitted_30d"], mid["readmission_rate"]) == (15, 14, 2, 0.142857)
    assert (old["encounters"], old["eligible_encounters"], old["readmitted_30d"], old["readmission_rate"]) == (14, 13, 1, 0.076923)
    assert [r["small_n"] for r in rows] == [True, False, False]  # 10 < 11
    assert young["id"] == 6  # age_order


def test_readmissions_by_other_groups(api: TestClient) -> None:
    types = by_label(get(api, "/analytics/readmissions", group_by="admission_type")["data"])
    assert (types["Emergency"]["encounters"], types["Emergency"]["eligible_encounters"], types["Emergency"]["readmission_rate"]) == (30, 27, 0.185185)
    urgent = types["Urgent"]
    assert (urgent["encounters"], urgent["readmitted_30d"], urgent["readmission_rate"], urgent["small_n"]) == (9, 0, 0.0, True)
    disp = {r["id"]: r for r in get(api, "/analytics/readmissions", group_by="discharge_disposition")["data"]}
    assert (disp[1]["encounters"], disp[1]["eligible_encounters"], disp[1]["readmission_rate"]) == (36, 36, 0.138889)
    for expired in (11, 13, 14):  # no eligible encounters: the rate is null, never 0
        assert (disp[expired]["encounters"], disp[expired]["eligible_encounters"], disp[expired]["readmission_rate"]) == (1, 0, None)
    spec = by_label(get(api, "/analytics/readmissions", group_by="specialty")["data"])
    assert (spec["Cardiology"]["encounters"], spec["Cardiology"]["readmission_rate"]) == (10, 0.222222)
    assert (spec["Unknown"]["encounters"], spec["Unknown"]["readmission_rate"]) == (29, 0.111111)


def test_months_are_chronological_and_match_an_independent_count(api: TestClient) -> None:
    rows = get(api, "/analytics/readmissions", group_by="month")["data"]
    labels = [r["label"] for r in rows]
    assert labels == sorted(labels)
    expected: dict[str, int] = {}
    for i in range(1, 40):
        expected[admission_of(i).strftime("%Y-%m")] = expected.get(admission_of(i).strftime("%Y-%m"), 0) + 1
    assert {r["label"]: r["encounters"] for r in rows} == expected and labels[0] == "2005-01"
    assert all(r["encounters"] >= 1 for r in rows)  # empty months are omitted, not zero-filled


def test_admissions_trend_month_and_year(api: TestClient) -> None:
    months = get(api, "/analytics/admissions-trend")["data"]
    years = get(api, "/analytics/admissions-trend", granularity="year")["data"]
    assert sum(m["encounters"] for m in months) == sum(y["encounters"] for y in years) == 39
    expected_years: dict[str, int] = {}
    for i in range(1, 40):
        expected_years[str(admission_of(i).year)] = expected_years.get(str(admission_of(i).year), 0) + 1
    assert {y["label"]: y["encounters"] for y in years} == expected_years
    assert api.get("/analytics/admissions-trend", params={"granularity": "week"}, headers=auth_header(api, "ana")).status_code == 422


def test_length_of_stay_with_histogram(api: TestClient) -> None:
    rows = get(api, "/analytics/length-of-stay", group_by="age_group")["data"]
    young, mid, old = rows
    assert (young["avg_length_of_stay"], young["min_length_of_stay"], young["max_length_of_stay"]) == (3.0, 1, 5)
    assert young["histogram"] == [2, 2, 2, 2, 2] + [0] * 9 and len(young["histogram"]) == 14
    assert (old["avg_length_of_stay"], old["histogram"][:5]) == (3.142857, [2, 3, 3, 3, 3])
    assert all(sum(r["histogram"]) == r["encounters"] for r in rows)
    assert young["small_n"] is True and mid["small_n"] is False


def test_length_of_stay_overall_is_one_server_side_histogram(api: TestClient) -> None:
    (row,) = get(api, "/analytics/length-of-stay", group_by="overall")["data"]
    assert row["label"] == "All encounters" and row["encounters"] == 39 and row["avg_length_of_stay"] == 3.051282
    assert row["histogram"][:5] == [7, 8, 8, 8, 8] and sum(row["histogram"]) == 39  # ids 1..39 by (id % 5) + 1
    assert (row["min_length_of_stay"], row["max_length_of_stay"]) == (1, 5)


def test_medications_endpoint(api: TestClient) -> None:
    data = get(api, "/analytics/medications")["data"]
    drugs = [(r["label"], r["encounters"], r["eligible_encounters"], r["readmitted_30d"], r["readmission_rate"]) for r in data["top_drugs"]]
    assert drugs == [("insulin", 5, 5, 4, 0.8), ("metformin", 2, 2, 1, 0.5)]
    insulin = data["insulin_status"]
    assert [r["label"] for r in insulin] == ["No", "Steady", "Up", "Down"]
    assert [(r["encounters"], r["eligible_encounters"], r["readmitted_30d"]) for r in insulin] == [(34, 31, 1), (3, 3, 2), (1, 1, 1), (1, 1, 1)]
    assert insulin[0]["readmission_rate"] == 0.032258
    a1c = data["a1c_result"]
    assert [(r["label"], r["encounters"], r["readmitted_30d"]) for r in a1c] == [("None", 36, 3), ("Norm", 2, 1), (">8", 1, 1)]
    assert sum(r["encounters"] for r in insulin) == sum(r["encounters"] for r in a1c) == 39


def test_utilization_buckets(api: TestClient) -> None:
    rows = get(api, "/analytics/utilization")["data"]
    assert [r["label"] for r in rows] == ["0", "1", "2", "3+"]
    assert [(r["encounters"], r["eligible_encounters"], r["readmitted_30d"], r["readmission_rate"]) for r in rows] == [
        (34, 31, 0, 0.0), (2, 2, 2, 1.0), (1, 1, 1, 1.0), (2, 2, 2, 1.0)]
    assert [r["small_n"] for r in rows] == [False, True, True, True]


# ---- invariants: no fan-out, no lost groups -------------------------------------------------------------------
@pytest.mark.parametrize("filters", [{}, {"age_group": "[70-80)"}, {"admission_type_id": 1},
                                     {"date_from": "2005-03-01", "date_to": "2005-12-31"}])
def test_group_counts_always_add_up_to_the_filtered_total(api: TestClient, filters: dict) -> None:
    total = get(api, "/analytics/summary", **filters)["data"]["total_encounters"]
    assert total > 0
    for group_by in ("age_group", "admission_type", "admission_source", "discharge_disposition", "specialty", "month"):
        rows = get(api, "/analytics/readmissions", group_by=group_by, **filters)["data"]
        assert sum(r["encounters"] for r in rows) == total, group_by
        assert sum(r["eligible_encounters"] for r in rows) == get(api, "/analytics/summary", **filters)["data"]["eligible_encounters"]
    for group_by in ("age_group", "admission_type", "admission_source", "specialty"):
        assert sum(r["encounters"] for r in get(api, "/analytics/length-of-stay", group_by=group_by, **filters)["data"]) == total
    for endpoint in ("admissions-trend",):
        assert sum(r["encounters"] for r in get(api, f"/analytics/{endpoint}", **filters)["data"]) == total
    assert sum(r["encounters"] for r in get(api, "/analytics/utilization", **filters)["data"]) == total
    meds = get(api, "/analytics/medications", **filters)["data"]
    assert sum(r["encounters"] for r in meds["insulin_status"]) == total == sum(r["encounters"] for r in meds["a1c_result"])


def test_monthly_encounters_sum_to_the_summary_for_the_same_window(api: TestClient) -> None:
    window = {"date_from": "2005-02-01", "date_to": "2005-09-30"}
    months = get(api, "/analytics/admissions-trend", **window)["data"]
    assert sum(m["encounters"] for m in months) == get(api, "/analytics/summary", **window)["data"]["total_encounters"]
    assert months[0]["label"] >= "2005-02" and months[-1]["label"] <= "2005-09"


def test_soft_deleted_rows_and_deleted_patients_never_count(api: TestClient, users_db: Engine) -> None:
    assert get(api, "/analytics/summary")["data"]["total_encounters"] == 39  # id 40 is deleted
    api.delete("/encounters/1", headers=auth_header(api, "admin"))
    assert get(api, "/analytics/summary")["data"]["total_encounters"] == 38
    api.delete("/patients/100", headers=auth_header(api, "admin"))  # patient 100 owns encounters 21, 22, 23
    assert get(api, "/analytics/summary")["data"]["total_encounters"] == 35


# ---- access, validation, privacy ------------------------------------------------------------------------------
@pytest.mark.parametrize("params", [{"group_by": "race"}, {"group_by": "gender"}, {"group_by": "patient_nbr"},
                                    {"group_by": "age_group; DROP TABLE x"}, {"age_group": "old"},
                                    {"date_from": "2005-05-01", "date_to": "2005-01-01"}, {"admission_type_id": 0}])
def test_invalid_parameters_are_422(api: TestClient, params: dict) -> None:
    r = api.get("/analytics/readmissions", params=params, headers=auth_header(api, "admin"))
    assert r.status_code == 422 and set(r.json()["error"]) == {"code", "message", "details"}


def test_all_roles_can_read_but_no_token_cannot(api: TestClient) -> None:
    for user in ("admin", "ops", "ana"):
        assert api.get("/analytics/summary", headers=auth_header(api, user)).status_code == 200
    assert api.get("/analytics/summary").status_code == 401


def test_no_demographics_anywhere_in_analytics(api: TestClient) -> None:
    for url in ("/analytics/summary", "/analytics/admissions-trend", "/analytics/length-of-stay", "/analytics/readmissions",
                "/analytics/medications", "/analytics/utilization"):
        text = api.get(url, headers=auth_header(api, "ana")).text.lower()
        assert "race" not in text and "gender" not in text and "caucasian" not in text and "patient_nbr" not in text
