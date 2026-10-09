"""Weekly report job: readmission_summary and admissions_trend as XLSX and CSV into data/reports/.

    python scripts/run_weekly_reports.py [--triggered-by airflow]

Uses the same generator as the API (etl.reports.generate_report), writes one report_runs row per file, and exits non-zero
if anything fails (so Airflow shows the task red).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.database import get_engine  # noqa: E402
from etl import jobs  # noqa: E402
from etl.pipeline import configure_logging  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the weekly reports")
    parser.add_argument("--triggered-by", default="airflow")
    args = parser.parse_args(argv)
    configure_logging()
    results = jobs.run_weekly_reports(get_engine(), triggered_by=args.triggered_by)
    for r in results:
        sys.stdout.write(f"wrote {r.filename} ({r.row_count} rows)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
