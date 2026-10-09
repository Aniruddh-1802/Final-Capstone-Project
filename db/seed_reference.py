"""Load the three ID lookup tables from data/reference/IDs_mapping.csv. Idempotent.

Run from the repository root:  python db/seed_reference.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import Engine, select  # noqa: E402
from sqlalchemy.dialects.mysql import insert as mysql_insert  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import create_all, get_engine  # noqa: E402
from app.models import RefAdmissionSource, RefAdmissionType, RefDischargeDisposition  # noqa: E402
from etl.extract import read_id_mappings  # noqa: E402
from utils.logging_config import setup_logging  # noqa: E402

log = logging.getLogger("seed_reference")
EXPIRED_OR_HOSPICE_IDS = frozenset({11, 13, 14, 19, 20, 21})
DEFAULT_PATH = ROOT / "data" / "reference" / "IDs_mapping.csv"


def seed_reference(engine: Engine, path: Path = DEFAULT_PATH) -> dict[str, int]:
    """Upsert the lookup rows and return the row count of each table afterwards."""
    tables = read_id_mappings(path)
    models = {
        "admission_type": RefAdmissionType,
        "admission_source": RefAdmissionSource,
        "discharge_disposition": RefDischargeDisposition,
    }
    counts: dict[str, int] = {}
    with Session(engine) as session, session.begin():
        for name, model in models.items():
            rows = [{"id": int(r.id), "description": r.description} for r in tables[name].itertuples()]
            if name == "discharge_disposition":
                for row in rows:
                    row["is_expired_or_hospice"] = row["id"] in EXPIRED_OR_HOSPICE_IDS
            stmt = mysql_insert(model).values(rows)
            update_cols = {c: stmt.inserted[c] for c in rows[0] if c != "id"}
            session.execute(stmt.on_duplicate_key_update(**update_cols))
            counts[name] = len(session.execute(select(model.id)).all())
    log.info("Reference tables loaded: %s", counts)
    return counts


if __name__ == "__main__":
    setup_logging("seed_reference", log_dir=ROOT / "logs")
    eng = get_engine()
    create_all(eng)
    seed_reference(eng)
