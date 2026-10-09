"""Environment smoke test: Python version, MySQL connection, CREATE/INSERT/SELECT/DROP round trip.

Run from the repository root:  python scripts/smoke_test.py
Prints PASS/FAIL per check and exits non-zero if any check fails.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import create_engine, text  # noqa: E402

from app.config import get_settings  # noqa: E402
from utils.logging_config import setup_logging  # noqa: E402

logger = setup_logging("smoke_test")
TABLE = "smoke_test_tmp"


def report(name: str, ok: bool, detail: str = "") -> bool:
    """Log one PASS/FAIL line."""
    logger.info("%s  %s %s", "PASS" if ok else "FAIL", name, detail)
    return ok


def main() -> int:
    results: list[bool] = []

    ok = sys.version_info >= (3, 10)
    results.append(report("Python version", ok, sys.version.split()[0] + " (need 3.10+)"))

    try:
        settings = get_settings()
    except Exception as exc:  # missing .env / DATABASE_URL
        results.append(report("Settings (.env)", False, str(exc).splitlines()[0]))
        return 1
    results.append(report("Settings (.env)", True))

    try:
        engine = create_engine(settings.database_url, pool_pre_ping=True,
                               connect_args={"connect_timeout": 5})
        with engine.connect() as conn:
            user, db = conn.execute(text("SELECT CURRENT_USER(), DATABASE()")).one()
        results.append(report("MySQL connection", True, f"user={user} db={db}"))
        results.append(report("Not connected as root", not str(user).startswith("root@"), str(user)))
    except Exception as exc:
        results.append(report("MySQL connection", False, type(exc).__name__ + ": " + str(exc)[:150]))
        return 1

    try:
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
            conn.execute(text(f"CREATE TABLE {TABLE} (id INT PRIMARY KEY, note VARCHAR(20))"))
            conn.execute(text(f"INSERT INTO {TABLE} (id, note) VALUES (:i, :n)"), {"i": 1, "n": "ok"})
            row = conn.execute(text(f"SELECT note FROM {TABLE} WHERE id = :i"), {"i": 1}).scalar_one()
            conn.execute(text(f"DROP TABLE {TABLE}"))
        results.append(report("CREATE/INSERT/SELECT/DROP round trip", row == "ok"))
    except Exception as exc:
        results.append(report("CREATE/INSERT/SELECT/DROP round trip", False, str(exc)[:150]))

    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
