"""KPI SQL tests on the 30-row fixture loaded into healthcare_test."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import Engine, text

import seed_reference
from app.services.kpi_sql import KPI_SQL_PATH, load_named_queries, run_query
from etl.pipeline import run_pipeline

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini_diabetic.csv"
EXPIRED = [11, 13, 14, 19, 20, 21]
QUERIES = load_named_queries()


@pytest.fixture()
def db(clean_db: Engine, tmp_path: Path) -> Engine:
    seed_reference.seed_reference(clean_db)
    assert run_pipeline(FIXTURE, engine=clean_db, rejected_dir=tmp_path).status == "SUCCESS"
    return clean_db


def q(db: Engine, name: str) -> list[dict]:
    with db.connect() as conn:
        return run_query(conn, QUERIES[name])


def test_headline_matches_pandas_on_fixture(db: Engine) -> None:
    raw = pd.read_csv(FIXTURE, keep_default_na=False, na_values=["?", ""])
    eligible = ~raw["discharge_disposition_id"].isin(EXPIRED)
    h = q(db, "headline")[0]
    assert h["total_encounters"] == 30 and h["unique_patients"] == 28  # patients != encounters
    assert h["eligible_encounters"] == 26 == eligible.sum()
    n30 = int((raw["readmitted"].eq("<30") & eligible).sum())
    assert h["readmitted_30d_count"] == n30
    assert h["readmission_rate_30d"] == pytest.approx(n30 / 26, abs=1e-6)
    assert h["readmission_rate_30d"] != pytest.approx(n30 / 30, abs=1e-3)  # not the all-encounters rate
    assert h["avg_length_of_stay"] == pytest.approx(raw["time_in_hospital"].mean(), abs=1e-6)


def test_soft_delete_drops_headline_by_exactly_one_and_undo_restores(db: Engine) -> None:
    before = q(db, "headline")[0]["total_encounters"]
    with db.begin() as conn:
        conn.execute(text("UPDATE encounters SET is_deleted = 1 WHERE encounter_id = 5"))
    assert q(db, "headline")[0]["total_encounters"] == before - 1
    with db.begin() as conn:
        conn.execute(text("UPDATE encounters SET is_deleted = 0 WHERE encounter_id = 5"))
    assert q(db, "headline")[0]["total_encounters"] == before


def test_deleted_patient_hides_all_their_encounters(db: Engine) -> None:
    with db.begin() as conn:
        conn.execute(text("UPDATE patients SET is_deleted = 1 WHERE patient_nbr = 1001"))  # has 3 encounters
    h = q(db, "headline")[0]
    assert h["total_encounters"] == 27 and h["unique_patients"] == 27


def test_age_groups_in_clinical_order(db: Engine) -> None:
    groups = [r["age_group"] for r in q(db, "by_age_group")]
    assert groups[0] == "[0-10)" and groups[-1] == "[90-100)"
    assert [r["age_order"] for r in q(db, "by_age_group")] == sorted(r["age_order"] for r in q(db, "by_age_group"))


def test_expired_group_has_no_eligible_encounters_and_null_rate(db: Engine) -> None:
    rows = {r["discharge_disposition_id"]: r for r in q(db, "by_discharge_disposition")}
    assert rows[11]["eligible_encounters"] == 0 and rows[11]["readmission_rate_30d"] is None
    assert rows[1]["eligible_encounters"] == rows[1]["encounters"]


def test_medication_and_utilisation_queries(db: Engine) -> None:
    insulin = {r["insulin_status"]: r["encounters"] for r in q(db, "insulin_status")}
    assert insulin == {"No": 28, "Up": 1, "Down": 1}  # fixture: encounter 3 insulin Up, encounter 22 insulin Down
    buckets = {r["prior_inpatient_visits"]: r["encounters"] for r in q(db, "prior_inpatient")}
    assert buckets == {"0": 29, "2": 1}  # encounter 29 has two prior inpatient visits
    assert sum(r["encounters"] for r in q(db, "a1c_result")) == 30
    drugs = q(db, "top_drugs")
    assert drugs[0] == {**drugs[0], "drug_name": "insulin", "encounters": 2}  # ties broken by drug name
    assert {d["drug_name"] for d in drugs} == {"insulin", "metformin", "glyburide", "glipizide", "glyburide_metformin",
                                               "glipizide_metformin", "glimepiride_pioglitazone",
                                               "metformin_rosiglitazone"}


def test_frequent_patients_returns_counts_only(db: Engine) -> None:
    row = q(db, "frequent_patients")[0]
    assert row == {"patients_with_3plus_encounters": 1, "encounters_of_those_patients": 3}


def test_time_queries(db: Engine) -> None:
    months = q(db, "monthly_trend")
    assert sum(m["encounters"] for m in months) == 30 and [m["month"] for m in months] == sorted(m["month"] for m in months)
    moving = q(db, "monthly_moving_average")
    assert moving[0]["rate_3m_moving_avg"] == moving[0]["readmission_rate_30d"]
    assert sum(y["encounters"] for y in q(db, "yearly_trend")) == 30


def test_sql_file_rules_every_query_reads_from_views_only() -> None:
    sql = KPI_SQL_PATH.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in sql.splitlines() if not ln.strip().startswith("--"))
    assert not re.search(r"\b(FROM|JOIN)\s+(encounters|patients|encounter_outcomes)\b", code, re.IGNORECASE)
    assert "SELECT *" not in code.upper()
    assert "race" not in code.lower() and "gender" not in code.lower()
    assert len(QUERIES) >= 14 and all(qq.description for qq in QUERIES.values())
