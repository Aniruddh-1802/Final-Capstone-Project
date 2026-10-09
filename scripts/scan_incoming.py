"""DAG task 1 (scan_for_new_files): report how many new files are waiting and remember the current max run id.

Prints exactly one JSON line as its LAST output line, which Airflow stores as the task's XCom, e.g.
    {"new_files": 2, "files": ["a.csv", "b.csv"], "after_run_id": 17}
Always exits 0 (finding no file is not an error). Run from the repository root with PYTHONPATH=src.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.config import get_settings  # noqa: E402
from app.database import get_engine  # noqa: E402
from etl import jobs  # noqa: E402
from etl.pipeline import configure_logging  # noqa: E402


def main() -> int:
    configure_logging()
    engine = get_engine()
    files = jobs.pending_files(engine)
    marker = jobs.max_run_id(engine)
    sys.stdout.write(json.dumps({"new_files": len(files), "files": [f.name for f in files], "after_run_id": marker}) + "\n")
    return 0


if __name__ == "__main__":
    get_settings()
    sys.exit(main())
