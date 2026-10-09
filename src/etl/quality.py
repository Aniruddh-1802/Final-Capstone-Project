"""Data-quality rules DQ01-DQ13: vectorised masks, quarantine of rejected rows, per-run summary.

Operates on a standardised batch DataFrame (see ``etl.transform.standardise_columns``). No database access.
Rule responses: reject (row removed), correct (value set to NULL), flag (kept, counted) or measure (summary only).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd

from etl.transform import AGE_BRACKETS, MEDICATION_COLUMNS

log = logging.getLogger(__name__)

DEFAULT_MAX_REJECT_RATIO = 0.20
MAX_ISSUES_PER_RULE = 500
WINDOW_START = pd.Timestamp("1999-01-01")
WINDOW_END = pd.Timestamp("2008-12-31")
DISCHARGE_GRACE_DAYS = 14  # a stay of up to 14 days may end after the last admission day
VALID_READMITTED = ("NO", ">30", "<30")
VALID_GENDER = ("Male", "Female", "Unknown", "Unknown/Invalid")
VALID_MED_STATUS = ("No", "Steady", "Up", "Down")
VALID_GLUCOSE = ("None", "Norm", ">200", ">300")
VALID_A1C = ("None", "Norm", ">7", ">8")
ALL_DRUG_COLUMNS = MEDICATION_COLUMNS + ["examide", "citoglipton"]
# (min, max) inclusive. Caps are about 2x the maximum seen in the full source file (see docs/data_profile.md).
NUMERIC_RANGES: dict[str, tuple[int, int]] = {
    "time_in_hospital": (1, 14),
    "num_lab_procedures": (0, 250),
    "num_procedures": (0, 20),
    "num_medications": (0, 150),
    "number_outpatient": (0, 100),
    "number_emergency": (0, 150),
    "number_inpatient": (0, 50),
    "number_diagnoses": (0, 30),
}
REFERENCE_COLUMNS = {
    "admission_type_id": "admission_type",
    "admission_source_id": "admission_source",
    "discharge_disposition_id": "discharge_disposition",
}
# ICD-9: 1-3 digits (source dropped leading zeros, e.g. '38' for 038), V-codes and E-codes, optional decimals.
ICD9_PATTERN = r"^(?:\d{1,3}(?:\.\d{1,2})?|V\d{1,2}(?:\.\d{1,2})?|E\d{3}(?:\.\d{1,2})?)$"
DIAG_COLUMNS = ["diag_1", "diag_2", "diag_3"]


class BatchRejectedError(Exception):
    """Raised when the rejected share exceeds the allowed ratio: the whole file fails and nothing is loaded."""

    def __init__(self, summary: dict, rejected: pd.DataFrame, issues: list[dict]) -> None:
        self.summary, self.rejected, self.issues = summary, rejected, issues
        super().__init__(
            f"Batch rejected: reject ratio {summary['reject_ratio']:.3f} exceeds the allowed "
            f"{summary['max_reject_ratio']:.3f} ({summary['rows_rejected']} of {summary['rows_in']} rows)")


@dataclass(frozen=True)
class RuleResult:
    """Outcome of one rule: which rows fire, how it is handled and which column=value caused it."""

    mask: pd.Series
    rule_name: str
    severity: str
    action: str  # rejected | corrected | flagged
    detail: pd.Series
    reason: str


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    """Column coerced to numbers; anything non-numeric (or a missing column) becomes NaN."""
    if col not in df.columns:
        return pd.Series(float("nan"), index=df.index)
    return pd.to_numeric(df[col], errors="coerce")


def _first_failing(df: pd.DataFrame, checks: dict[str, pd.Series]) -> tuple[pd.Series, pd.Series]:
    """Combine per-column failure masks; detail names the first failing column as ``column=value``."""
    mask = pd.Series(False, index=df.index)
    detail = pd.Series("", index=df.index, dtype=object)
    for col, bad in checks.items():
        fresh = bad & ~mask
        if fresh.any():
            shown = df.loc[fresh, col].map(lambda v: "<missing>" if pd.isna(v) else str(v))  # astype(str) keeps NaN
            detail[fresh] = col + "=" + shown
        mask |= bad
    return mask, detail


def _result(df: pd.DataFrame, checks: dict[str, pd.Series], name: str, severity: str, action: str,
            reason: str) -> RuleResult:
    mask, detail = _first_failing(df, checks)
    return RuleResult(mask, name, severity, action, detail, reason)


def _dates(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Parse admission_date and discharge_date (ISO); unparseable or missing values become NaT."""
    def parse(col: str) -> pd.Series:
        if col not in df.columns:
            return pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
        return pd.to_datetime(df[col], format="%Y-%m-%d", errors="coerce")
    return parse("admission_date"), parse("discharge_date")


def dq01_missing_ids(df: pd.DataFrame, **_: object) -> RuleResult:
    """DQ01: missing or non-numeric encounter_id / patient_nbr."""
    checks = {}
    for col in ("encounter_id", "patient_nbr"):
        n = _num(df, col)
        checks[col] = n.isna() | ((n % 1) != 0) | (n <= 0)
    return _result(df, checks, "DQ01", "error", "rejected", "Missing or non-numeric encounter_id/patient_nbr")


def dq02_duplicate_encounter(df: pd.DataFrame, **_: object) -> RuleResult:
    """DQ02: duplicate encounter_id inside the file - keep the first, reject the rest."""
    ids = _num(df, "encounter_id")
    return _result(df, {"encounter_id": ids.notna() & ids.duplicated(keep="first")}, "DQ02", "error", "rejected",
                   "Duplicate encounter_id in file (first occurrence kept)")


def dq03_invalid_codes(df: pd.DataFrame, reference_ids: dict[str, set[int]], **_: object) -> RuleResult:
    """DQ03: admission type / source / discharge disposition id not in the reference tables."""
    checks = {}
    for col, ref in REFERENCE_COLUMNS.items():
        n = _num(df, col)
        checks[col] = n.isna() | ~n.isin(list(reference_ids[ref]))
    return _result(df, checks, "DQ03", "error", "rejected", "Code not found in reference table")


def dq04_invalid_categorical(df: pd.DataFrame, **_: object) -> RuleResult:
    """DQ04: readmitted, age, gender, medication status, lab results, change/diabetes flags outside allowed sets."""
    allowed: dict[str, tuple[str, ...]] = {
        "readmitted": VALID_READMITTED, "age": tuple(AGE_BRACKETS), "gender": VALID_GENDER,
        "max_glu_serum": VALID_GLUCOSE, "a1c_result": VALID_A1C, "med_changed": ("Ch", "No"),
        "diabetes_med": ("Yes", "No"),
    }
    allowed.update({c: VALID_MED_STATUS for c in ALL_DRUG_COLUMNS})
    checks = {c: ~df[c].isin(values) for c, values in allowed.items() if c in df.columns}
    return _result(df, checks, "DQ04", "error", "rejected", "Invalid categorical value")


def dq05_numeric_range(df: pd.DataFrame, **_: object) -> RuleResult:
    """DQ05: time_in_hospital outside 1-14 or a count negative / above its cap (non-numeric also fails)."""
    checks = {}
    for col, (low, high) in NUMERIC_RANGES.items():
        n = _num(df, col)
        checks[col] = n.isna() | (n < low) | (n > high)
    return _result(df, checks, "DQ05", "error", "rejected", "Numeric value missing or outside plausible range")


def icd9_bad_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Per diagnosis column: True where a code is present but not a valid ICD-9 format."""
    return {c: df[c].notna() & ~df[c].astype(str).str.match(ICD9_PATTERN) for c in DIAG_COLUMNS if c in df.columns}


def dq06_icd_format(df: pd.DataFrame, **_: object) -> RuleResult:
    """DQ06: malformed ICD-9 code -> set to NULL and flag as corrected (the row is kept)."""
    return _result(df, icd9_bad_masks(df), "DQ06", "warning", "corrected", "Invalid ICD-9 format; value set to NULL")


def dq07_missing_dates(df: pd.DataFrame, **_: object) -> RuleResult:
    """DQ07: admission_date or discharge_date missing or unparseable."""
    adm, dis = _dates(df)
    return _result(df, {"admission_date": adm.isna(), "discharge_date": dis.isna()}, "DQ07", "error", "rejected",
                   "Admission or discharge date missing or unparseable")


def dq08_outside_window(df: pd.DataFrame, today: pd.Timestamp | None = None, **_: object) -> RuleResult:
    """DQ08: dates outside the 1999-01-01..2008-12-31 study window (discharge may run 14 days over) or in the future."""
    now = today or pd.Timestamp(date.today())
    adm, dis = _dates(df)
    last_discharge = WINDOW_END + timedelta(days=DISCHARGE_GRACE_DAYS)
    checks = {
        "admission_date": adm.notna() & ((adm < WINDOW_START) | (adm > WINDOW_END) | (adm > now)),
        "discharge_date": dis.notna() & ((dis < WINDOW_START) | (dis > last_discharge) | (dis > now)),
    }
    return _result(df, checks, "DQ08", "error", "rejected", "Date outside study window or in the future")


def dq09_discharge_before_admission(df: pd.DataFrame, **_: object) -> RuleResult:
    """DQ09: discharge_date earlier than admission_date."""
    adm, dis = _dates(df)
    return _result(df, {"discharge_date": adm.notna() & dis.notna() & (dis < adm)}, "DQ09", "error", "rejected",
                   "Discharge date earlier than admission date")


def dq10_stay_mismatch(df: pd.DataFrame, **_: object) -> RuleResult:
    """DQ10: (discharge - admission) in days differs from time_in_hospital.

    Evaluated only on rows whose dates and stay length are individually valid (DQ05/DQ07/DQ09 own the rest), so one
    underlying fault is reported by one rule.
    """
    adm, dis = _dates(df)
    stay = _num(df, "time_in_hospital")
    low, high = NUMERIC_RANGES["time_in_hospital"]
    evaluable = adm.notna() & dis.notna() & (dis >= adm) & stay.between(low, high)
    return _result(df, {"time_in_hospital": evaluable & ((dis - adm).dt.days != stay)}, "DQ10", "error", "rejected",
                   "Date difference does not match time_in_hospital")


def dq12_unknown_gender(df: pd.DataFrame, **_: object) -> RuleResult:
    """DQ12: gender 'Unknown/Invalid' - kept as Unknown, flagged."""
    return _result(df, {"gender": df["gender"].eq("Unknown/Invalid")}, "DQ12", "info", "flagged",
                   "Gender Unknown/Invalid kept as Unknown")


def dq13_conflicting_demographics(df: pd.DataFrame, **_: object) -> RuleResult:
    """DQ13: same patient_nbr with conflicting race or gender across rows - first non-null kept, flagged."""
    checks = {}
    for col in ("race", "gender"):
        distinct = df.groupby("patient_nbr")[col].transform("nunique")
        checks[col] = distinct.gt(1) & df[col].notna()
    return _result(df, checks, "DQ13", "warning", "flagged", "Conflicting race/gender for the same patient; first kept")


RULES: list[Callable[..., RuleResult]] = [
    dq01_missing_ids, dq02_duplicate_encounter, dq03_invalid_codes, dq04_invalid_categorical, dq05_numeric_range,
    dq06_icd_format, dq07_missing_dates, dq08_outside_window, dq09_discharge_before_admission, dq10_stay_mismatch,
    dq12_unknown_gender, dq13_conflicting_demographics,
]


def reference_ids_from_mappings(tables: dict[str, pd.DataFrame]) -> dict[str, set[int]]:
    """Convert ``extract.read_id_mappings`` output into the sets ``validate`` needs."""
    return {name: set(map(int, t["id"])) for name, t in tables.items()}


def build_dq_issues(df: pd.DataFrame, results: list[RuleResult], missing: dict[str, int]) -> list[dict]:
    """Records ready for dq_issues (loader adds run_id). At most 500 examples per rule; true counts live in the summary."""
    issues: list[dict] = []
    ids = _num(df, "encounter_id")
    for r in results:
        for idx in r.mask[r.mask].index[:MAX_ISSUES_PER_RULE]:
            col, _, bad = str(r.detail[idx]).partition("=")
            issues.append({
                "encounter_id": int(ids[idx]) if pd.notna(ids[idx]) else None, "rule_name": r.rule_name,
                "severity": r.severity, "column_name": col or None, "bad_value": bad[:255] if bad else None,
                "action": r.action,
            })
    for col, n in missing.items():
        if n:
            issues.append({"encounter_id": None, "rule_name": "DQ11", "severity": "info", "column_name": col,
                           "bad_value": str(n), "action": "metric"})
    return issues


def validate(df: pd.DataFrame, reference_ids: dict[str, set[int]],
             max_reject_ratio: float = DEFAULT_MAX_REJECT_RATIO, today: pd.Timestamp | None = None,
             enforce: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Apply DQ01-DQ13 and return ``(clean_df, rejected_df, dq_summary)``.

    ``rejected_df`` keeps the original columns plus ``rule_name`` and ``reason``; a row failing several rules
    appears once per rule but is removed once. ``dq_summary['issues']`` holds dq_issues records. If the reject ratio
    exceeds ``max_reject_ratio`` and ``enforce`` is true, ``BatchRejectedError`` is raised carrying the summary.
    """
    work = df.reset_index(drop=True)
    results = [rule(work, reference_ids=reference_ids, today=today) for rule in RULES]
    reject_mask = pd.Series(False, index=work.index)
    parts = []
    for r in results:
        if r.action == "rejected" and r.mask.any():
            reject_mask |= r.mask
            part = work[r.mask].copy()
            part["rule_name"] = r.rule_name
            part["reason"] = r.reason + " (" + r.detail[r.mask] + ")"
            parts.append(part)
    rejected = pd.concat(parts) if parts else work.iloc[0:0].assign(rule_name="", reason="")
    clean = work[~reject_mask].copy()
    corrected = 0
    for col, bad in icd9_bad_masks(work).items():
        fix = bad & ~reject_mask
        clean.loc[fix[fix].index.intersection(clean.index), col] = pd.NA
        corrected += int(fix.sum())
    flagged = sum(int((r.mask & ~reject_mask).sum()) for r in results if r.action == "flagged")
    missing = {str(c): int(n) for c, n in work.isna().sum().items()}
    n_in, n_rej = len(work), int(reject_mask.sum())
    summary = {
        "rows_in": n_in, "rows_clean": len(clean), "rows_rejected": n_rej,
        "reject_ratio": (n_rej / n_in) if n_in else 0.0, "max_reject_ratio": max_reject_ratio,
        "counts_per_rule": {r.rule_name: int(r.mask.sum()) for r in results},
        "missing_by_column": missing, "corrected_count": corrected, "flagged_count": flagged,
    }
    issues = build_dq_issues(work, results, missing)
    summary["issues"] = issues
    log.info("Validated %d rows: %d clean, %d rejected (%.2f%%), %d corrected, %d flagged", n_in, len(clean), n_rej,
             summary["reject_ratio"] * 100, corrected, flagged)
    if enforce and summary["reject_ratio"] > max_reject_ratio:
        raise BatchRejectedError(summary, rejected, issues)
    return clean.reset_index(drop=True), rejected.reset_index(drop=True), summary


def write_rejected(rejected: pd.DataFrame, batch_name: str, rejected_dir: str | Path) -> Path | None:
    """Write ``<batch>_rejected.csv`` (with rule_name and reason columns) and return its path; None if nothing rejected."""
    if rejected.empty:
        return None
    folder = Path(rejected_dir)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{Path(batch_name).stem}_rejected.csv"
    out = rejected.copy()
    for col in ("encounter_id", "patient_nbr"):  # a NaN makes pandas read ids as floats; write them as integers
        if col in out.columns and pd.api.types.is_float_dtype(out[col]):
            out[col] = out[col].astype("Int64")
    out.to_csv(target, index=False)
    log.info("Quarantined %d rejection records to %s", len(rejected), target)
    return target
