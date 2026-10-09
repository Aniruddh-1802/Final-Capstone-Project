"""Create data/incoming/faulty_batch.csv from a held-back batch by injecting known faults.

Injected (on disjoint rows, so each fault is caught by exactly one rule):
  5 duplicate encounter_ids (DQ02), 5 unknown discharge_disposition_id = 99 (DQ03), 5 negative time_in_hospital
  (DQ05), 5 discharge dates before admission (DQ09), 5 malformed ICD-9 codes (DQ06, corrected not rejected),
  3 missing patient_nbr (DQ01). Exact counts and the affected encounter_ids go to faulty_batch.json.

Run from the repository root:  python scripts/make_faulty_batch.py [source_csv]
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from utils.logging_config import setup_logging  # noqa: E402

SEED = 42
DEFAULT_SOURCE = ROOT / "data" / "held_back" / "encounters_batch_003.csv"
OUT_CSV = ROOT / "data" / "incoming" / "faulty_batch.csv"
OUT_JSON = ROOT / "data" / "incoming" / "faulty_batch.json"
log = logging.getLogger("make_faulty_batch")


def inject_faults(df: pd.DataFrame, seed: int = SEED) -> tuple[pd.DataFrame, dict]:
    """Return ``(faulty_df, manifest)``. ``df`` must hold text values (read with dtype=str, keep_default_na=False)."""
    out = df.copy()
    rng = np.random.default_rng(seed)
    n = len(out)
    pool = rng.permutation(np.arange(n // 2, n))  # fault rows come from the second half; duplicates copy from the first
    take = iter(pool)

    def rows(k: int) -> list[int]:
        return [int(next(take)) for _ in range(k)]

    dup_rows, disp_rows, neg_rows, date_rows, icd_rows, pat_rows = rows(5), rows(5), rows(5), rows(5), rows(5), rows(3)
    sources = [int(i) for i in rng.choice(np.arange(0, n // 2), size=5, replace=False)]
    manifest: dict = {"source_rows": n, "injected": {}, "encounter_ids": {}}

    for target, source in zip(dup_rows, sources):
        out.loc[target, "encounter_id"] = out.loc[source, "encounter_id"]
    out.loc[disp_rows, "discharge_disposition_id"] = "99"
    out.loc[neg_rows, "time_in_hospital"] = "-3"
    admission = pd.to_datetime(out.loc[date_rows, "admission_date"])
    out.loc[date_rows, "discharge_date"] = (admission - pd.Timedelta(days=2)).dt.strftime("%Y-%m-%d")
    out.loc[icd_rows, "diag_1"] = ["ABC", "12345.6", "V", "E1", "250.123"]
    out.loc[pat_rows, "patient_nbr"] = ""

    for name, idx, rule in (("duplicate_encounter_id", dup_rows, "DQ02"), ("unknown_discharge_disposition", disp_rows, "DQ03"),
                            ("negative_time_in_hospital", neg_rows, "DQ05"), ("discharge_before_admission", date_rows, "DQ09"),
                            ("malformed_icd9", icd_rows, "DQ06"), ("missing_patient_nbr", pat_rows, "DQ01")):
        manifest["injected"][name] = {"count": len(idx), "rule": rule}
        manifest["encounter_ids"][name] = [str(v) for v in out.loc[idx, "encounter_id"]]
    manifest["expected_rejected_rows"] = 23  # all faults except the malformed ICD codes, which are corrected not rejected
    manifest["expected_corrected_cells"] = 5
    return out, manifest


SEVERE_SOURCE = ROOT / "data" / "held_back" / "encounters_batch_004.csv"
SEVERE_CSV = ROOT / "data" / "incoming" / "severe_faulty_batch.csv"


def make_severe(source: Path = SEVERE_SOURCE, out: Path = SEVERE_CSV, share: float = 0.30) -> int:
    """Corrupt ``readmitted`` in ``share`` of the rows so the file is over MAX_REJECT_RATIO and is refused WHOLE (nothing loads).

    Used to demonstrate the failure path of the scheduled pipeline. Returns the number of corrupted rows.
    """
    df = pd.read_csv(source, dtype=str, keep_default_na=False)
    bad = df.sample(frac=share, random_state=SEED).index
    df.loc[bad, "readmitted"] = "MAYBE"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    log.info("wrote %s: %d of %d rows corrupted (%.0f%%)", out.name, len(bad), len(df), share * 100)
    return len(bad)


def main(source: Path = DEFAULT_SOURCE) -> None:
    df = pd.read_csv(source, dtype=str, keep_default_na=False)
    faulty, manifest = inject_faults(df)
    manifest["source_file"] = source.name
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    faulty.to_csv(OUT_CSV, index=False)
    OUT_JSON.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("Wrote %s (%d rows) and %s", OUT_CSV.name, len(faulty), OUT_JSON.name)
    for name, info in manifest["injected"].items():
        log.info("  %-32s %d x %s", name, info["count"], info["rule"])


if __name__ == "__main__":
    setup_logging("make_faulty_batch", log_dir=ROOT / "logs")
    if "--severe" in sys.argv:
        make_severe()  # over the reject threshold: the whole file is refused
    else:
        main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE)
