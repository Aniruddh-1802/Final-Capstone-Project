"""Prove the SQL KPIs equal an independent pandas calculation from the raw CSV.

The pandas side reads data/raw/diabetic_data.csv directly (never the database), applies the same eligibility rule,
and is restricted to the encounter_ids that are currently loaded and active, so partial loads still compare fairly.

Run from the repository root:  python scripts/verify_kpis.py     (exit code 1 if any metric FAILS)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.database import get_engine  # noqa: E402
from app.services.kpi_sql import load_named_queries, run_query  # noqa: E402
from etl.extract import NA_VALUES  # noqa: E402
from etl.transform import AGE_BRACKETS, EXPIRED_OR_HOSPICE_IDS  # noqa: E402
from utils.logging_config import setup_logging  # noqa: E402

log = logging.getLogger("verify_kpis")
RAW = ROOT / "data" / "raw" / "diabetic_data.csv"
TOLERANCE = 5e-6  # SQL rates are rounded to 6 decimals


def pandas_metrics(raw: pd.DataFrame) -> dict[str, float]:
    """Headline numbers from raw rows; eligibility = discharge id not in the expired/hospice list."""
    eligible = ~raw["discharge_disposition_id"].isin(EXPIRED_OR_HOSPICE_IDS)
    lt30, any_re = raw["readmitted"].eq("<30"), raw["readmitted"].isin(["<30", ">30"])
    return {
        "total_encounters": len(raw), "unique_patients": raw["patient_nbr"].nunique(),
        "avg_length_of_stay": raw["time_in_hospital"].mean(), "avg_num_medications": raw["num_medications"].mean(),
        "eligible_encounters": int(eligible.sum()), "readmitted_30d_count": int((lt30 & eligible).sum()),
        "readmission_rate_30d": (lt30 & eligible).sum() / eligible.sum(),
        "any_readmission_rate": (any_re & eligible).sum() / eligible.sum(),
    }


def pandas_by_age(raw: pd.DataFrame) -> pd.DataFrame:
    """Per age bracket: encounters, avg LOS, eligible, 30-day count and rate, in clinical order."""
    work = raw.assign(eligible=~raw["discharge_disposition_id"].isin(EXPIRED_OR_HOSPICE_IDS))
    work["lt30"] = work["readmitted"].eq("<30") & work["eligible"]
    grouped = work.groupby("age").agg(encounters=("encounter_id", "size"), avg_length_of_stay=("time_in_hospital", "mean"),
                                      eligible_encounters=("eligible", "sum"), readmitted_30d_count=("lt30", "sum"))
    grouped["readmission_rate_30d"] = grouped["readmitted_30d_count"] / grouped["eligible_encounters"]
    return grouped.reindex([b for b in AGE_BRACKETS if b in grouped.index])


def check(name: str, sql_value: float, pandas_value: float, results: list[bool]) -> None:
    ok = abs(float(sql_value) - float(pandas_value)) <= TOLERANCE
    results.append(ok)
    log.info("%s  %-40s sql=%-12s pandas=%s", "PASS" if ok else "FAIL", name, round(float(sql_value), 6),
             round(float(pandas_value), 6))


def check_api(engine: Engine, expected: dict[str, float], ages: pd.DataFrame, results: list[bool]) -> None:
    """Call /analytics/summary and /analytics/readmissions in-process (admin token) and compare with pandas."""
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.security import create_access_token

    with engine.connect() as conn:
        admin_id = conn.execute(text("SELECT user_id FROM app_users WHERE role = 'administrator' AND is_active = 1 "
                                     "ORDER BY user_id LIMIT 1")).scalar_one()
    client = TestClient(create_app(engine=engine))
    headers = {"Authorization": f"Bearer {create_access_token(admin_id, 'administrator')}"}
    summary = client.get("/analytics/summary", headers=headers).json()["data"]
    api_keys = {"total_encounters": "total_encounters", "unique_patients": "unique_patients",
                "avg_length_of_stay": "avg_length_of_stay", "avg_num_medications": "avg_num_medications",
                "eligible_encounters": "eligible_encounters", "readmitted_30d_count": "readmitted_30d",
                "readmission_rate_30d": "readmission_rate_30d", "any_readmission_rate": "any_readmission_rate"}
    for pandas_key, api_key in api_keys.items():
        check(f"API summary.{api_key}", summary[api_key], expected[pandas_key], results)
    rows = client.get("/analytics/readmissions", params={"group_by": "age_group"}, headers=headers).json()["data"]
    results.append([r["label"] for r in rows] == list(ages.index))
    log.info("%s  API age groups in clinical order", "PASS" if results[-1] else "FAIL")
    for row in rows:
        exp = ages.loc[row["label"]]
        check(f"API age {row['label']}.encounters", row["encounters"], exp["encounters"], results)
        check(f"API age {row['label']}.rate", row["readmission_rate"], exp["readmission_rate_30d"], results)


def main() -> int:
    engine = get_engine()
    queries = load_named_queries()
    with engine.connect() as conn:
        headline = run_query(conn, queries["headline"])[0]
        by_age = run_query(conn, queries["by_age_group"])
        loaded = pd.Series(conn.execute(text("SELECT encounter_id FROM v_active_encounters")).scalars().all())
    raw = pd.read_csv(RAW, keep_default_na=False, na_values=NA_VALUES, low_memory=False)
    raw = raw[raw["encounter_id"].isin(loaded)]
    log.info("Comparing %d active encounters loaded in MySQL against the raw CSV", len(raw))

    results: list[bool] = []
    expected = pandas_metrics(raw)
    for key, value in expected.items():
        check(f"headline.{key}", headline[key], value, results)
    ages = pandas_by_age(raw)
    results.append([r["age_group"] for r in by_age] == list(ages.index))
    log.info("%s  age groups in clinical order: %s", "PASS" if results[-1] else "FAIL", [r["age_group"] for r in by_age])
    for row in by_age:
        exp = ages.loc[row["age_group"]]
        for col in ("encounters", "avg_length_of_stay", "eligible_encounters", "readmitted_30d_count", "readmission_rate_30d"):
            check(f"age {row['age_group']}.{col}", row[col], exp[col], results)

    check_api(engine, expected, ages, results)

    wrong = expected["readmitted_30d_count"] / expected["total_encounters"]
    log.info("Wrong denominator (all encounters) would give %.6f instead of %.6f: off by %.6f",
             wrong, expected["readmission_rate_30d"], expected["readmission_rate_30d"] - wrong)
    log.info("%d/%d checks passed", sum(results), len(results))
    return 0 if all(results) else 1


if __name__ == "__main__":
    setup_logging("verify_kpis", log_dir=ROOT / "logs")
    sys.exit(main())
