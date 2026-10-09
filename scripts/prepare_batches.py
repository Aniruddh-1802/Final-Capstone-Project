"""Prepare simulated feed files from the raw dataset (the raw file is never modified).

* Generates SIMULATED admission_date (seed 42): N dates between 1999-01-01 and 2008-12-31 with mild yearly
  growth and a winter peak, SORTED ascending, then assigned in encounter_id order.
* discharge_date = admission_date + time_in_hospital days.
* Writes encounters_batch_000_initial.csv (~80%) plus four incremental batches in encounter_id order:
  000, 001, 002 -> data/incoming; 003, 004 -> data/held_back (kept for the live demo).
* Writes a ~500-row seeded sample to data/sample_data/sample_encounters.csv.

Run from the repository root:  python scripts/prepare_batches.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from utils.logging_config import setup_logging  # noqa: E402

SEED = 42
START, END = "1999-01-01", "2008-12-31"
INITIAL_SHARE = 0.80
SAMPLE_ROWS = 500
RAW = ROOT / "data" / "raw" / "diabetic_data.csv"
INCOMING = ROOT / "data" / "incoming"
HELD_BACK = ROOT / "data" / "held_back"
SAMPLE = ROOT / "data" / "sample_data" / "sample_encounters.csv"

log = logging.getLogger("prepare_batches")


def simulate_admission_dates(n: int, seed: int = SEED) -> pd.Series:
    """Return ``n`` sorted simulated dates with mild yearly growth and a winter (mid-January) peak."""
    days = pd.date_range(START, END, freq="D")
    years_in = (days - days[0]).days.to_numpy() / 365.25
    growth = 1.0 + 0.04 * years_in  # about +4% per year
    winter = 1.0 + 0.15 * np.cos(2 * np.pi * (days.dayofyear.to_numpy() - 15) / 365.25)
    weights = growth * winter
    rng = np.random.default_rng(seed)
    picks = rng.choice(len(days), size=n, replace=True, p=weights / weights.sum())
    return pd.Series(days[np.sort(picks)])


def add_simulated_dates(df: pd.DataFrame, seed: int = SEED) -> pd.DataFrame:
    """Return a copy ordered by encounter_id with admission_date and discharge_date (ISO strings) appended."""
    out = df.sort_values("encounter_id", key=lambda s: s.astype("int64")).reset_index(drop=True)
    admission = simulate_admission_dates(len(out), seed)
    stay = pd.to_timedelta(out["time_in_hospital"].astype("int64"), unit="D")
    out["admission_date"] = admission.dt.strftime("%Y-%m-%d")
    out["discharge_date"] = (admission + stay).dt.strftime("%Y-%m-%d")
    return out


def split_batches(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split into the initial batch (~80%) and four equal incremental batches, in encounter order."""
    cut = int(len(df) * INITIAL_SHARE)
    batches = {"encounters_batch_000_initial.csv": df.iloc[:cut]}
    rest = df.iloc[cut:]
    for i, part in enumerate(np.array_split(np.arange(len(rest)), 4), start=1):
        batches[f"encounters_batch_{i:03d}.csv"] = rest.iloc[part]
    return batches


def main() -> None:
    # Read as text so '?' and 'None' are written back exactly as in the source feed.
    raw = pd.read_csv(RAW, dtype=str, keep_default_na=False)
    prepared = add_simulated_dates(raw)
    for folder in (INCOMING, HELD_BACK, SAMPLE.parent):
        folder.mkdir(parents=True, exist_ok=True)
    for name, part in split_batches(prepared).items():
        number = int(name.split("_")[2][:3])
        target = INCOMING if number <= 2 else HELD_BACK
        part.to_csv(target / name, index=False)
        log.info("%-36s %6d rows  %s -> %s  encounter_id %s..%s  (%s)", name, len(part),
                 part["admission_date"].iloc[0], part["admission_date"].iloc[-1],
                 part["encounter_id"].iloc[0], part["encounter_id"].iloc[-1], target.name)
    sample = prepared.sample(n=SAMPLE_ROWS, random_state=SEED).sort_values("encounter_id", key=lambda s: s.astype("int64"))
    sample.to_csv(SAMPLE, index=False)
    log.info("sample_encounters.csv %d rows", len(sample))


if __name__ == "__main__":
    setup_logging("prepare_batches", log_dir=ROOT / "logs")
    main()
