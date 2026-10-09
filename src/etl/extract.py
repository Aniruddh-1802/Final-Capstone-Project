"""Extract layer: read source files into DataFrames. No cleaning beyond reading correctly."""
from __future__ import annotations

import csv
import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

NA_VALUES = ["?", ""]
DIAG_COLUMNS = ["diag_1", "diag_2", "diag_3"]
ID_TABLES = {
    "admission_type_id": "admission_type",
    "discharge_disposition_id": "discharge_disposition",
    "admission_source_id": "admission_source",
}

RAW_COLUMNS = [
    "encounter_id", "patient_nbr", "race", "gender", "age", "weight", "admission_type_id",
    "discharge_disposition_id", "admission_source_id", "time_in_hospital", "payer_code", "medical_specialty",
    "num_lab_procedures", "num_procedures", "num_medications", "number_outpatient", "number_emergency",
    "number_inpatient", "diag_1", "diag_2", "diag_3", "number_diagnoses", "max_glu_serum", "A1Cresult",
    "metformin", "repaglinide", "nateglinide", "chlorpropamide", "glimepiride", "acetohexamide", "glipizide",
    "glyburide", "tolbutamide", "pioglitazone", "rosiglitazone", "acarbose", "miglitol", "troglitazone",
    "tolazamide", "examide", "citoglipton", "insulin", "glyburide-metformin", "glipizide-metformin",
    "glimepiride-pioglitazone", "metformin-rosiglitazone", "metformin-pioglitazone", "change", "diabetesMed",
    "readmitted",
]
# Columns a batch file needs beyond the raw dataset: simulated dates added by scripts/prepare_batches.py.
BATCH_COLUMNS = RAW_COLUMNS + ["admission_date", "discharge_date"]


class MissingColumnsError(ValueError):
    """Raised when a file lacks required columns (a column check, not a row check)."""

    def __init__(self, missing: list[str], path: Path | str) -> None:
        self.missing = missing
        super().__init__(f"{path}: missing required columns: {', '.join(missing)}")


def read_id_mappings(path: str | Path) -> dict[str, pd.DataFrame]:
    """Parse IDs_mapping.csv, which stacks three tables separated by blank (or comma-only) rows.

    Each block starts with its own header row (``<name>_id,description``). Descriptions may be quoted and
    contain commas; leading/trailing spaces are stripped. Returns ``{"admission_type": df, ...}`` where each
    DataFrame has integer ``id`` and text ``description`` columns.
    """
    blocks: dict[str, list[tuple[int, str]]] = {}
    current: str | None = None
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.reader(fh):
            cells = [c.strip() for c in row]
            if not any(cells):
                current = None
                continue
            if cells[0] in ID_TABLES and len(cells) > 1 and cells[1] == "description":
                current = ID_TABLES[cells[0]]
                blocks[current] = []
                continue
            if current is None:
                raise ValueError(f"{path}: data row before a header row: {row!r}")
            blocks[current].append((int(cells[0]), ",".join(cells[1:]).strip()))
    missing = set(ID_TABLES.values()) - set(blocks)
    if missing:
        raise ValueError(f"{path}: missing tables: {sorted(missing)}")
    frames = {name: pd.DataFrame(rows, columns=["id", "description"]) for name, rows in blocks.items()}
    for name, frame in frames.items():
        if frame["id"].duplicated().any():
            raise ValueError(f"{path}: duplicate ids in {name}")
        log.info("Read %d rows for lookup table %s", len(frame), name)
    return frames


def read_batch(path: str | Path, required: list[str] | None = None) -> pd.DataFrame:
    """Read a raw or prepared batch CSV with the contract's missing-value handling.

    ``'?'`` and blank cells become NaN; the text ``None`` in the lab columns stays a value. Diagnosis codes
    are read as strings. ``required`` defaults to the 50 raw columns plus the two simulated date columns; a
    ``MissingColumnsError`` is raised before any row is processed if one is absent.
    """
    path = Path(path)
    header = pd.read_csv(path, nrows=0).columns.tolist()
    needed = BATCH_COLUMNS if required is None else required
    missing = [c for c in needed if c not in header]
    if missing:
        raise MissingColumnsError(missing, path)
    df = pd.read_csv(
        path, keep_default_na=False, na_values=NA_VALUES, low_memory=False,
        dtype={**{c: str for c in DIAG_COLUMNS}, "payer_code": str, "medical_specialty": str,
               "race": str, "gender": str},
    )
    log.info("Read %d rows x %d columns from %s", len(df), df.shape[1], path.name)
    return df
