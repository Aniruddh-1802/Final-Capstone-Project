"""Fill audit_logs with synthetic rows so audit-log queries can be measured at a realistic size (L12).

SAFETY: refuses to run unless the database name contains 'perf'. Synthetic rows are labelled with request_id 'synthetic'.
Run (PowerShell):  $env:DATABASE_URL = '<url of healthcare_perf>'; python scripts/perf_seed_audit.py [rows]
"""
from __future__ import annotations

import logging
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import insert  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import get_engine  # noqa: E402
from app.models import AuditLog  # noqa: E402
from utils.logging_config import setup_logging  # noqa: E402

log = logging.getLogger("perf_seed_audit")
USERS = [("admin", "administrator"), ("ops", "clinical_ops"), ("nurse.a", "clinical_ops"), ("nurse.b", "clinical_ops"),
         ("ops2", "clinical_ops"), ("ops3", "clinical_ops"), ("lead", "administrator")]
ACTIONS = ["CREATE", "UPDATE", "UPDATE", "UPDATE", "DELETE", "EXPORT"]


def main(rows: int) -> None:
    name = make_url(get_settings().database_url).database or ""
    if "perf" not in name:
        raise SystemExit(f"refusing to write synthetic rows into database '{name}' (name must contain 'perf')")
    rng = random.Random(7)
    now = datetime.now().replace(microsecond=0)
    batch: list[dict] = []
    engine = get_engine()
    with engine.begin() as conn:
        for i in range(rows):
            username, role = rng.choice(USERS)
            eid = rng.randrange(1, 450_000_000)
            batch.append({"created_at": now - timedelta(seconds=rng.randrange(0, 200 * 86400)), "username": username,
                          "role": role, "action": rng.choice(ACTIONS), "entity_type": rng.choice(["encounter", "patient"]),
                          "entity_id": str(eid), "before_json": {"readmitted": "NO"}, "after_json": {"readmitted": "<30"},
                          "request_id": "synthetic", "ip_address": "127.0.0.1"})
            if len(batch) == 5000:
                conn.execute(insert(AuditLog), batch)
                batch = []
        if batch:
            conn.execute(insert(AuditLog), batch)
    log.info("inserted %d synthetic audit rows into %s", rows, name)


if __name__ == "__main__":
    setup_logging("perf_seed_audit", log_dir=ROOT / "logs")
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 300_000)
