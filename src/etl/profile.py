"""Profile diabetic_data.csv. Reproduces every number quoted in docs/data_profile.md.

Run from the repository root:  python src/etl/profile.py
The raw file is only read, never modified.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.logging_config import setup_logging  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "diabetic_data.csv"
IDS = ROOT / "data" / "reference" / "IDs_mapping.csv"
EXPIRED_HOSPICE = [11, 13, 14, 19, 20, 21]
LAB_COLS = ["max_glu_serum", "A1Cresult"]
MED_COLS = [
    "metformin", "repaglinide", "nateglinide", "chlorpropamide", "glimepiride", "acetohexamide",
    "glipizide", "glyburide", "tolbutamide", "pioglitazone", "rosiglitazone", "acarbose", "miglitol",
    "troglitazone", "tolazamide", "examide", "citoglipton", "insulin", "glyburide-metformin",
    "glipizide-metformin", "glimepiride-pioglitazone", "metformin-rosiglitazone", "metformin-pioglitazone",
]
COUNT_COLS = ["time_in_hospital", "num_lab_procedures", "num_procedures", "num_medications",
              "number_outpatient", "number_emergency", "number_inpatient", "number_diagnoses"]

log = logging.getLogger("profile")


def load_raw(path: Path = RAW) -> pd.DataFrame:
    """Load with the contract's missing-value handling ('?' and blank are missing, 'None' is a value)."""
    return pd.read_csv(path, keep_default_na=False, na_values=["?", ""], low_memory=False,
                       dtype={"diag_1": str, "diag_2": str, "diag_3": str, "payer_code": str})


def none_behaviour(path: Path = RAW) -> pd.DataFrame:
    """Compare 'None' handling: pandas default read versus the contract read."""
    default = pd.read_csv(path, usecols=LAB_COLS)
    correct = pd.read_csv(path, usecols=LAB_COLS, keep_default_na=False, na_values=["?", ""])
    return pd.DataFrame({
        "missing_default_read": default.isna().sum(),
        "missing_correct_read": correct.isna().sum(),
        "literal_None_rows": (correct == "None").sum(),
    })


def read_id_tables(path: Path = IDS) -> dict[str, pd.DataFrame]:
    """Minimal split of the three stacked tables (the full parser is in etl.extract, L3)."""
    tables: dict[str, list[list[str]]] = {}
    current: str | None = None
    import csv
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row or all(c.strip() == "" for c in row):
                current = None
                continue
            if row[0].endswith("_id") and row[1] == "description":
                current = row[0]
                tables[current] = []
            elif current:
                tables[current].append([row[0], ",".join(row[1:]).strip()])
    return {k: pd.DataFrame(v, columns=["id", "description"]) for k, v in tables.items()}


def profile() -> dict[str, object]:
    """Compute and log every figure used in the data profile; return them as a dict."""
    df = load_raw()
    out: dict[str, object] = {}

    out["rows"], out["columns"] = df.shape
    log.info("shape=%s", df.shape)
    log.info("columns=%s", list(df.columns))

    miss = df.isna().sum()
    out["missing"] = miss[miss > 0].sort_values(ascending=False)
    log.info("missing per column (correct read):\n%s", pd.DataFrame(
        {"missing": miss[miss > 0], "pct": (miss[miss > 0] / len(df) * 100).round(2)}).sort_values("missing", ascending=False))

    out["none_behaviour"] = none_behaviour()
    log.info("'None' behaviour:\n%s", out["none_behaviour"])

    out["encounter_unique"] = df["encounter_id"].is_unique
    out["distinct_patients"] = df["patient_nbr"].nunique()
    per_patient = df.groupby("patient_nbr").size()
    out["max_encounters_per_patient"] = int(per_patient.max())
    out["patients_with_multiple"] = int((per_patient > 1).sum())
    top = per_patient.idxmax()
    log.info("encounter_id unique=%s; distinct patient_nbr=%d; patients with >1 encounter=%d; max per patient=%d (patient %s)",
             out["encounter_unique"], out["distinct_patients"], out["patients_with_multiple"],
             out["max_encounters_per_patient"], top)

    for col in ["readmitted", "gender", "race", "age", "admission_type_id", "discharge_disposition_id", "admission_source_id"]:
        log.info("value counts %s:\n%s", col, df[col].value_counts(dropna=False).sort_index())

    # Readmission shares: two ways (value_counts and boolean mask) must agree.
    shares = df["readmitted"].value_counts(normalize=True).round(4)
    lt30_a = int(df["readmitted"].value_counts()["<30"])
    lt30_b = int((df["readmitted"] == "<30").sum())
    assert lt30_a == lt30_b, "two methods disagree"
    out["readmitted_shares"] = shares
    out["readmitted_lt30"] = lt30_a
    log.info("readmitted shares:\n%s\n<30 count (value_counts == mask): %d", shares, lt30_a)

    expired = df["discharge_disposition_id"].isin(EXPIRED_HOSPICE)
    out["expired_hospice_n"] = int(expired.sum())
    out["expired_hospice_pct"] = round(float(expired.mean() * 100), 2)
    out["eligible_n"] = int((~expired).sum())
    out["rate_all"] = round(lt30_b / len(df) * 100, 2)
    out["rate_eligible"] = round(int(((df["readmitted"] == "<30") & ~expired).sum()) / int((~expired).sum()) * 100, 2)
    out["expired_by_id"] = df.loc[expired, "discharge_disposition_id"].value_counts().sort_index()
    log.info("expired/hospice discharges: %d (%.2f%%); eligible: %d; <30 rate over ALL=%.2f%% vs ELIGIBLE=%.2f%%",
             out["expired_hospice_n"], out["expired_hospice_pct"], out["eligible_n"], out["rate_all"], out["rate_eligible"])
    log.info("expired/hospice by id:\n%s", out["expired_by_id"])

    out["time_in_hospital"] = df["time_in_hospital"].agg(["min", "max", "mean"]).round(3)
    log.info("numeric ranges:\n%s", df[COUNT_COLS].agg(["min", "max", "mean"]).round(2).T)

    nunique = df.nunique(dropna=True)
    out["constant_cols"] = list(nunique[nunique == 1].index)
    log.info("constant columns: %s", out["constant_cols"])
    dominant = {c: round(float(df[c].value_counts(normalize=True, dropna=True).iloc[0] * 100), 2) for c in MED_COLS}
    out["med_dominant_no_pct"] = dominant
    log.info("medication columns (count=%d) share of top value:\n%s", len(MED_COLS), pd.Series(dominant).sort_values(ascending=False))
    out["med_values"] = sorted(set(pd.unique(df[MED_COLS].values.ravel())))
    log.info("medication value set: %s", out["med_values"])

    diag = df[["diag_1", "diag_2", "diag_3"]]
    out["diag_v_codes"] = int(diag.apply(lambda s: s.str.startswith("V", na=False)).sum().sum())
    out["diag_e_codes"] = int(diag.apply(lambda s: s.str.startswith("E", na=False)).sum().sum())
    out["diag_decimal"] = int(diag.apply(lambda s: s.str.contains(r"\.", na=False)).sum().sum())
    log.info("diagnosis codes: V=%d E=%d with decimal point=%d", out["diag_v_codes"], out["diag_e_codes"], out["diag_decimal"])

    out["dup_rows_excl_id"] = int(df.drop(columns="encounter_id").duplicated().sum())
    log.info("fully duplicated rows ignoring encounter_id: %d", out["dup_rows_excl_id"])

    for name, tbl in read_id_tables().items():
        log.info("IDs_mapping table %s: %d rows; ids=%s", name, len(tbl), list(tbl["id"]))
        data_ids = set(df[name].astype(str).unique())
        log.info("  ids in data but not in mapping: %s", sorted(data_ids - set(tbl["id"])))
        log.info("  mapping rows described as NULL/Not Available/Not Mapped/Unknown: %s",
                 tbl.loc[tbl["description"].str.contains("NULL|Not Available|Not Mapped|Unknown", case=False), "id"].tolist())
    return out


if __name__ == "__main__":
    setup_logging("profile", log_dir=ROOT / "logs")
    sys.exit(0 if profile() else 1)
