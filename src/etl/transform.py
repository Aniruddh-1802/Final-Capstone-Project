"""Transform layer: pure functions (DataFrame in, DataFrame out). No database, no file access, no printing.

Pipeline order: ``read_batch`` -> ``standardise_columns`` -> ``quality.validate`` -> ``build_tables``.
"""
from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)

DROPPED_COLUMNS = ["weight", "examide", "citoglipton"]
EXPIRED_OR_HOSPICE_IDS = (11, 13, 14, 19, 20, 21)
RENAMES = {"a1cresult": "a1c_result", "diabetesmed": "diabetes_med", "change": "med_changed"}
MEDICATION_COLUMNS = [
    "metformin", "repaglinide", "nateglinide", "chlorpropamide", "glimepiride", "acetohexamide", "glipizide",
    "glyburide", "tolbutamide", "pioglitazone", "rosiglitazone", "acarbose", "miglitol", "troglitazone",
    "tolazamide", "insulin", "glyburide_metformin", "glipizide_metformin", "glimepiride_pioglitazone",
    "metformin_rosiglitazone", "metformin_pioglitazone",
]  # 23 source drug columns minus the two constant ones (examide, citoglipton)
PRESCRIBED = ("Steady", "Up", "Down")
AGE_BRACKETS = [f"[{i}-{i + 10})" for i in range(0, 100, 10)]
AGE_ORDER = {bracket: order for order, bracket in enumerate(AGE_BRACKETS, start=1)}
ENCOUNTER_COLUMNS = [
    "encounter_id", "patient_nbr", "admission_date", "discharge_date", "age_group", "age_order",
    "admission_type_id", "discharge_disposition_id", "admission_source_id", "medical_specialty", "payer_code",
    "time_in_hospital", "num_lab_procedures", "num_procedures", "num_medications", "number_outpatient",
    "number_emergency", "number_inpatient", "number_diagnoses", "max_glu_serum", "a1c_result", "med_changed",
    "diabetes_med",
]


def standardise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with snake_case names: hyphens become underscores; A1Cresult, change, diabetesMed renamed."""
    out = df.copy()
    lowered = [c.strip().lower().replace("-", "_") for c in out.columns]
    out.columns = [RENAMES.get(c, c) for c in lowered]
    return out


def normalise_gender(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy where ``Unknown/Invalid`` becomes ``Unknown`` (missing stays missing)."""
    out = df.copy()
    out["gender"] = out["gender"].replace({"Unknown/Invalid": "Unknown"})
    return out


def derive_age_order(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``age_group`` (the bracket) and ``age_order`` 1-10; unrecognised brackets get a missing order."""
    out = df.copy()
    out["age_group"] = out["age"]
    out["age_order"] = out["age"].map(AGE_ORDER).astype("Int64")
    return out


def derive_outcome_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Add readmitted_30d, any_readmission and is_readmission_eligible (single definition for every consumer).

    Eligible is False when discharge_disposition_id is an expired or hospice code (11, 13, 14, 19, 20, 21).
    """
    out = df.copy()
    out["readmitted_30d"] = out["readmitted"].eq("<30")
    out["any_readmission"] = out["readmitted"].isin(["<30", ">30"])
    out["is_readmission_eligible"] = ~pd.to_numeric(out["discharge_disposition_id"]).isin(EXPIRED_OR_HOSPICE_IDS)
    return out


def melt_medications(df: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
    """Wide-to-long: one row per prescribed drug (Steady/Up/Down). ``No`` rows are not produced."""
    cols = [c for c in (columns or MEDICATION_COLUMNS) if c in df.columns]
    long = df.melt(id_vars="encounter_id", value_vars=cols, var_name="drug_name", value_name="dosage_status")
    long = long[long["dosage_status"].isin(PRESCRIBED)]
    return long.sort_values(["encounter_id", "drug_name"]).reset_index(drop=True)


def split_diagnoses(df: pd.DataFrame) -> pd.DataFrame:
    """diag_1..diag_3 -> rows (encounter_id, position 1-3, icd9_code). Codes stay strings; missing ones are skipped."""
    parts = []
    for position in (1, 2, 3):
        part = df[["encounter_id", f"diag_{position}"]].rename(columns={f"diag_{position}": "icd9_code"})
        part.insert(1, "position", position)
        parts.append(part)
    out = pd.concat(parts, ignore_index=True).dropna(subset=["icd9_code"])
    out["icd9_code"] = out["icd9_code"].astype(str)
    return out.sort_values(["encounter_id", "position"]).reset_index(drop=True)


def missing_value_report(df: pd.DataFrame) -> dict[str, int]:
    """Count, per column, the values read as missing ('?' or blank in the source file)."""
    return {str(col): int(n) for col, n in df.isna().sum().items()}


def _build_patients(df: pd.DataFrame) -> pd.DataFrame:
    """One row per patient_nbr; race/gender come from the first non-missing value across that patient's rows."""
    patients = df.sort_values("encounter_id").groupby("patient_nbr", as_index=False).agg(
        race=("race", "first"), gender=("gender", "first"))
    return patients.sort_values("patient_nbr").reset_index(drop=True)


def _build_encounters(df: pd.DataFrame) -> pd.DataFrame:
    """Encounter rows; specialty and payer stay as text (the loader resolves lookup ids)."""
    out = df[ENCOUNTER_COLUMNS].copy()
    out["admission_date"] = pd.to_datetime(out["admission_date"]).dt.date
    out["discharge_date"] = pd.to_datetime(out["discharge_date"]).dt.date
    out["med_changed"] = df["med_changed"].eq("Ch")
    out["diabetes_med"] = df["diabetes_med"].eq("Yes")
    return out.sort_values("encounter_id").reset_index(drop=True)


def build_tables(df: pd.DataFrame) -> dict[str, object]:
    """Turn a validated, standardised batch into table-shaped DataFrames plus the missing-value report.

    Keys: patients, encounters, diagnoses, encounter_medications, outcomes (DataFrames) and
    ``missing_report`` (dict). Input row count equals encounters and outcomes; patients equals distinct patient_nbr.
    """
    report = missing_value_report(df)  # before dropping, so weight's missingness is still recorded
    work = df.drop(columns=[c for c in DROPPED_COLUMNS if c in df.columns])
    work = derive_outcome_flags(derive_age_order(normalise_gender(work)))
    for key in ("encounter_id", "patient_nbr"):
        work[key] = work[key].astype("int64")
    outcomes = work[["encounter_id", "readmitted", "readmitted_30d", "any_readmission", "is_readmission_eligible"]]
    tables: dict[str, object] = {
        "patients": _build_patients(work),
        "encounters": _build_encounters(work),
        "diagnoses": split_diagnoses(work),
        "encounter_medications": melt_medications(work),
        "outcomes": outcomes.sort_values("encounter_id").reset_index(drop=True),
        "missing_report": report,
    }
    log.info("Built tables from %d rows: %s", len(df),
             {k: len(v) for k, v in tables.items() if isinstance(v, pd.DataFrame)})
    return tables
