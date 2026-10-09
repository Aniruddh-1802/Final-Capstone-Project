"""Create or replace the SQL views in the development database.

Run from the repository root:  python scripts/apply_views.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.database import create_views, get_engine  # noqa: E402
from utils.logging_config import setup_logging  # noqa: E402

if __name__ == "__main__":
    setup_logging("apply_views", log_dir=ROOT / "logs")
    create_views(get_engine())
    logging.getLogger("apply_views").info("Views v_active_encounters and v_readmission_base created")
