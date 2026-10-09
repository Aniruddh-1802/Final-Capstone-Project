"""DAG task check_quality / record_summary: inspect the pipeline runs created after a marker run id.

    python scripts/check_latest_run.py --after-run-id 17 [--max-reject-ratio 0.05] [--summary]

Exit code 0: no new runs (a successful no-op) or every new run is SUCCESS, reconciles and is under the reject limit.
Exit code 1: a run FAILED, is still RUNNING, does not reconcile, or rejected more than the limit. Airflow marks a task
failed only on a non-zero exit, so this script is where a quality problem turns the DAG red. ``--summary`` always exits 0
and only prints the counts (used by record_summary).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.database import get_engine  # noqa: E402
from etl import jobs  # noqa: E402
from etl.pipeline import configure_logging  # noqa: E402


def parse_marker(raw: str) -> int:
    """Accept a plain integer or the JSON line printed by scan_incoming.py (Airflow passes the XCom as text)."""
    text = raw.strip().strip("'\"")
    try:
        return int(text)
    except ValueError:
        return int(json.loads(text.replace("'", '"'))["after_run_id"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the pipeline runs created after a marker run id")
    parser.add_argument("--after-run-id", required=True, help="integer, or the JSON line from scan_incoming.py")
    parser.add_argument("--max-reject-ratio", type=float, default=jobs.DEFAULT_CHECK_REJECT_RATIO)
    parser.add_argument("--summary", action="store_true", help="print the counts and always exit 0")
    args = parser.parse_args(argv)
    configure_logging()
    result = jobs.check_runs(get_engine(), parse_marker(args.after_run_id), args.max_reject_ratio)
    for line in jobs.summary_lines(result):
        sys.stdout.write(line + "\n")
    if args.summary:
        return 0
    for problem in result.problems:
        sys.stderr.write(f"QUALITY CHECK FAILED: {problem}\n")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
