"""Create the L12 indexes from db/indexes.sql on the database in DATABASE_URL, skipping ones that already exist,
then refresh the views and the optimizer statistics.

Run from the repository root:  python scripts/apply_indexes.py
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import Engine, text  # noqa: E402

from app.database import create_views, get_engine  # noqa: E402
from app.services.kpi_sql import split_statements  # noqa: E402
from utils.logging_config import setup_logging  # noqa: E402

log = logging.getLogger("apply_indexes")
INDEX_SQL = ROOT / "db" / "indexes.sql"
_CREATE = re.compile(r"CREATE INDEX (\w+) ON (\w+) \(([^)]*)\)", re.IGNORECASE)


def parse_indexes(sql: str) -> list[tuple[str, str, list[str]]]:
    """Return (index_name, table, [columns]) for every CREATE INDEX in the file."""
    return [(m.group(1), m.group(2), [c.strip() for c in m.group(3).split(",")])
            for m in _CREATE.finditer("\n".join(split_statements(sql)))]


def apply_indexes(engine: Engine, sql_path: Path = INDEX_SQL) -> list[str]:
    """Create missing indexes; return the names created."""
    created: list[str] = []
    with engine.begin() as conn:
        for name, table, _ in parse_indexes(sql_path.read_text(encoding="utf-8-sig")):
            exists = conn.execute(text("SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() "
                                       "AND table_name = :t AND index_name = :i"), {"t": table, "i": name}).scalar_one()
            if exists:
                log.info("index %s already exists", name)
                continue
            statement = next(s for s in split_statements(sql_path.read_text(encoding="utf-8-sig")) if f" {name} " in s)
            conn.execute(text(statement))
            created.append(name)
            log.info("created index %s on %s", name, table)
        if created:
            tables = ", ".join(sorted({t for n, t, _ in parse_indexes(sql_path.read_text(encoding="utf-8-sig"))}))
            conn.execute(text(f"ANALYZE TABLE {tables}"))
    create_views(engine)
    return created


if __name__ == "__main__":
    setup_logging("apply_indexes", log_dir=ROOT / "logs")
    apply_indexes(get_engine())
