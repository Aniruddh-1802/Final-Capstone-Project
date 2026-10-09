"""Measure the frequent queries: EXPLAIN, EXPLAIN ANALYZE and the median of five timed runs (first run discarded).

SAFETY: read-only and refuses to run unless the database name contains 'perf'.
Run (PowerShell):  $env:DATABASE_URL = '<url of healthcare_perf>'; python scripts/perf_measure.py before  [out.json]
Writes JSON with every query's plans and timings; docs/performance_notes.md is assembled from two such files.
"""
from __future__ import annotations

import json
import logging
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import get_engine  # noqa: E402
from utils.logging_config import setup_logging  # noqa: E402

log = logging.getLogger("perf_measure")
RUNS = 6  # the first (cold) run is discarded, the median of the remaining five is reported

ELIGIBLE_RATE = ("SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END)")
QUERIES: dict[str, tuple[str, str]] = {
    "Q1 encounters list: date range, newest first (page 1)": (
        "SELECT encounter_id, patient_nbr, admission_date, age_group, time_in_hospital, readmitted FROM v_active_encounters "
        "WHERE admission_date >= '2005-03-01' AND admission_date <= '2005-03-31' "
        "ORDER BY admission_date DESC, encounter_id DESC LIMIT 25",
        "GET /encounters?date_from=2005-03-01&date_to=2005-03-31"),
    "Q2 patient lookup with encounters": (
        "SELECT encounter_id, admission_date, readmitted FROM v_active_encounters WHERE patient_nbr = 88785891 "
        "ORDER BY admission_date DESC, encounter_id DESC",
        "GET /patients/{id}/encounters"),
    "Q3 monthly trend for one year (dashboard filter)": (
        "SELECT DATE_FORMAT(admission_date, '%Y-%m') AS month, COUNT(*) AS encounters, "
        f"{ELIGIBLE_RATE} AS r30 FROM v_active_encounters "
        "WHERE admission_date >= '2005-01-01' AND admission_date <= '2005-12-31' GROUP BY DATE_FORMAT(admission_date, '%Y-%m') "
        "ORDER BY month",
        "GET /analytics/admissions-trend?date_from=2005-01-01&date_to=2005-12-31"),
    "Q4 readmission rate by age group (all data)": (
        f"SELECT age_order, age_group, COUNT(*) AS encounters, SUM(is_readmission_eligible) AS eligible, {ELIGIBLE_RATE} AS r30 "
        "FROM v_active_encounters GROUP BY age_order, age_group ORDER BY age_order",
        "GET /analytics/readmissions?group_by=age_group"),
    "Q5 audit log search by user and date": (
        "SELECT id, created_at, username, action, entity_type, entity_id FROM audit_logs WHERE username = 'ops' "
        "AND created_at >= (NOW() - INTERVAL 14 DAY) AND created_at < (NOW() - INTERVAL 7 DAY) "
        "ORDER BY created_at DESC, id DESC LIMIT 25",
        "GET /admin/audit-logs?user=ops&date_from=...&date_to=..."),
    "Q8 audit log newest first (no filter)": (
        "SELECT id, created_at, username, action, entity_type, entity_id FROM audit_logs "
        "ORDER BY created_at DESC, id DESC LIMIT 25",
        "GET /admin/audit-logs"),
    "Q9 audit trail of one record": (
        "SELECT id, created_at, username, action FROM audit_logs WHERE entity_type = 'encounter' AND entity_id = '123456' "
        "ORDER BY created_at DESC, id DESC LIMIT 25",
        "GET /admin/audit-logs?entity_type=encounter&entity_id=..."),
    "Q6 ICD-9 prefix search": (
        "SELECT v.encounter_id, v.admission_date FROM v_active_encounters v WHERE EXISTS (SELECT 1 FROM encounter_diagnoses d "
        "WHERE d.encounter_id = v.encounter_id AND d.icd9_code LIKE 'V57%') ORDER BY v.admission_date DESC, v.encounter_id DESC LIMIT 25",
        "GET /encounters?q=V57"),
    "Q7 top drugs with readmission rate": (
        f"SELECT m.drug_name, COUNT(*) AS encounters, {ELIGIBLE_RATE.replace('is_readmission_eligible', 'v.is_readmission_eligible').replace('readmitted_30d', 'v.readmitted_30d')} AS r30 "
        "FROM v_active_encounters v JOIN encounter_medications em ON em.encounter_id = v.encounter_id "
        "JOIN medications m ON m.medication_id = em.medication_id GROUP BY m.drug_name ORDER BY encounters DESC LIMIT 10",
        "GET /analytics/medications"),
}


def measure(conn: Any, sql: str) -> dict[str, Any]:
    """Plans plus timings for one query."""
    plan = [dict(r._mapping) for r in conn.execute(text("EXPLAIN " + sql))]
    analyze = "\n".join(r[0] for r in conn.execute(text("EXPLAIN ANALYZE " + sql)))
    timings = []
    for _ in range(RUNS):
        start = time.perf_counter()
        conn.execute(text(sql)).fetchall()
        timings.append((time.perf_counter() - start) * 1000)
    kept = timings[1:]
    rows_examined = sum(int(p["rows"] or 0) for p in plan if p.get("rows") is not None)
    return {"explain": [{k: (None if v is None else str(v)) for k, v in p.items()} for p in plan],
            "explain_analyze": analyze, "timings_ms": [round(t, 2) for t in timings],
            "median_ms": round(statistics.median(kept), 2), "estimated_rows_examined": rows_examined}


def main(label: str, out: Path) -> None:
    name = make_url(get_settings().database_url).database or ""
    if "perf" not in name:
        raise SystemExit(f"refusing to run against '{name}' (name must contain 'perf')")
    results: dict[str, Any] = {"label": label, "database": name, "queries": {}}
    with get_engine().connect() as conn:
        conn.execute(text("ANALYZE TABLE encounters, encounter_outcomes, encounter_diagnoses, encounter_medications, audit_logs"))
        for title, (sql, endpoint) in QUERIES.items():
            result = measure(conn, sql)
            result.update(sql=sql, endpoint=endpoint)
            results["queries"][title] = result
            log.info("%-55s median %8.2f ms  est. rows examined %s", title, result["median_ms"], result["estimated_rows_examined"])
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    log.info("wrote %s", out)


if __name__ == "__main__":
    setup_logging("perf_measure", log_dir=ROOT / "logs")
    main(sys.argv[1] if len(sys.argv) > 1 else "run", Path(sys.argv[2] if len(sys.argv) > 2 else f"perf_{sys.argv[1] if len(sys.argv) > 1 else 'run'}.json"))
