"""Tests for etl.extract and etl.transform using tests/fixtures/mini_diabetic.csv (30 rows)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from etl.extract import MissingColumnsError, read_batch, read_id_mappings
from etl.transform import (
    MEDICATION_COLUMNS, build_tables, derive_age_order, derive_outcome_flags, melt_medications,
    missing_value_report, normalise_gender, split_diagnoses, standardise_columns,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "mini_diabetic.csv"


@pytest.fixture(scope="module")
def raw() -> pd.DataFrame:
    return read_batch(FIXTURE)


@pytest.fixture(scope="module")
def std(raw: pd.DataFrame) -> pd.DataFrame:
    return standardise_columns(raw)


# ---- extract -----------------------------------------------------------------------------------------------
def test_read_batch_missing_markers_and_none_value(raw: pd.DataFrame) -> None:
    assert len(raw) == 30
    assert raw["weight"].isna().sum() == 29 and raw["weight"].notna().sum() == 1  # '?' -> NaN
    assert (raw["max_glu_serum"] == "None").sum() >= 1  # real value, not missing
    assert raw["max_glu_serum"].isna().sum() == 0 and raw["A1Cresult"].isna().sum() == 0


def test_read_batch_diagnoses_are_strings(raw: pd.DataFrame) -> None:
    assert raw["diag_1"].map(type).eq(str).all()
    assert "038" in set(raw["diag_2"].dropna())  # leading zero preserved


def test_read_batch_fails_fast_on_missing_columns(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("encounter_id,patient_nbr\n1,2\n", encoding="utf-8")
    with pytest.raises(MissingColumnsError) as exc:
        read_batch(bad)
    assert "race" in exc.value.missing and "admission_date" in exc.value.missing


def test_read_id_mappings_real_file() -> None:
    tables = read_id_mappings(ROOT / "data" / "reference" / "IDs_mapping.csv")
    assert {k: len(v) for k, v in tables.items()} == {
        "admission_type": 8, "discharge_disposition": 30, "admission_source": 25}
    disp = tables["discharge_disposition"].set_index("id")["description"]
    assert disp[19].startswith("Expired at home. Medicaid only, hospice")  # quoted comma kept
    assert tables["admission_source"].set_index("id")["description"][1] == "Physician Referral"  # stripped


def test_read_id_mappings_handles_trailing_blank_and_blank_separators(tmp_path: Path) -> None:
    f = tmp_path / "m.csv"
    f.write_text(
        'admission_type_id,description\n1,A\n\ndischarge_disposition_id,description\n2,"B, with comma"\n'
        ',\nadmission_source_id,description\n3, C \n\n', encoding="utf-8")
    t = read_id_mappings(f)
    assert t["discharge_disposition"].iloc[0]["description"] == "B, with comma"
    assert t["admission_source"].iloc[0]["description"] == "C"


# ---- transform ---------------------------------------------------------------------------------------------
def test_standardise_columns(std: pd.DataFrame) -> None:
    for col in ("a1c_result", "diabetes_med", "med_changed", "glyburide_metformin", "metformin_pioglitazone"):
        assert col in std.columns
    assert not any("-" in c or c != c.lower() for c in std.columns)


def test_normalise_gender(std: pd.DataFrame) -> None:
    out = normalise_gender(std)
    assert (out["gender"] == "Unknown").sum() == 1 and (out["gender"] == "Unknown/Invalid").sum() == 0
    assert (std["gender"] == "Unknown/Invalid").sum() == 1  # input untouched (pure)


def test_derive_age_order(std: pd.DataFrame) -> None:
    out = derive_age_order(std)
    mapping = dict(zip(out["age_group"], out["age_order"]))
    assert mapping["[0-10)"] == 1 and mapping["[70-80)"] == 8 and mapping["[90-100)"] == 10
    bad = derive_age_order(pd.DataFrame({"age": ["[5-15)"]}))
    assert bad["age_order"].isna().all()


def test_expired_disposition_is_not_eligible(std: pd.DataFrame) -> None:
    out = derive_outcome_flags(std)
    expired = out[out["discharge_disposition_id"].isin([11, 13, 14, 19, 20, 21])]
    assert len(expired) == 4 and not expired["is_readmission_eligible"].any()
    assert out.loc[out["discharge_disposition_id"] == 1, "is_readmission_eligible"].all()
    assert out["readmitted_30d"].sum() == 4  # '<30' rows only
    assert out["any_readmission"].sum() == 6  # four '<30' plus two '>30'
    assert not (out["readmitted_30d"] & ~out["any_readmission"]).any()


def test_melt_drops_no_and_keeps_prescribed(std: pd.DataFrame) -> None:
    long = melt_medications(std)
    assert set(long["dosage_status"]) <= {"Steady", "Up", "Down"}
    assert len(long) == 10
    row17 = long[long["encounter_id"] == 17]
    assert row17["drug_name"].tolist() == ["glyburide_metformin"]  # hyphen -> underscore, 'No' column absent
    assert len(MEDICATION_COLUMNS) == 21


def test_split_diagnoses_keeps_strings_and_positions(std: pd.DataFrame) -> None:
    diag = split_diagnoses(std)
    assert len(diag) == 86  # 90 slots minus 4 missing
    assert diag["icd9_code"].map(type).eq(str).all()
    row19 = diag[diag["encounter_id"] == 19].set_index("position")["icd9_code"]
    assert row19.to_dict() == {1: "V57", 2: "E909", 3: "250.83"}
    assert "038" in set(diag["icd9_code"]) and "8" in set(diag["icd9_code"])
    assert set(diag["position"]) == {1, 2, 3}


def test_missing_value_report_counts(raw: pd.DataFrame) -> None:
    report = missing_value_report(raw)
    assert report["weight"] == 29 and report["max_glu_serum"] == 0
    assert report["diag_3"] == 2 and report["race"] == 2


def test_build_tables_row_counts_and_shapes(std: pd.DataFrame) -> None:
    t = build_tables(std)
    enc, pat, out = t["encounters"], t["patients"], t["outcomes"]
    assert len(enc) == len(std) == len(out) == 30
    assert len(pat) == std["patient_nbr"].nunique() == 28
    assert pat["patient_nbr"].is_unique
    assert not {"weight", "examide", "citoglipton"} & set(enc.columns)
    assert t["missing_report"]["weight"] == 29  # reported even though the column is dropped
    assert enc["encounter_id"].dtype == "int64" and pat["patient_nbr"].dtype == "int64"
    assert enc["med_changed"].sum() == 2 and enc["diabetes_med"].sum() == 29
    assert str(enc["admission_date"].iloc[0]) == "2005-01-01"


def test_patients_take_first_non_null_race_and_gender(std: pd.DataFrame) -> None:
    pat = build_tables(std)["patients"].set_index("patient_nbr")
    assert pat.loc[1001, "race"] == "Caucasian"  # first row had '?' (missing); later rows fill it
    assert pat.loc[1010, "gender"] == "Unknown"
    assert pat["race"].isna().sum() == 1  # patient 1005 only


def test_lab_none_survives_build_tables(std: pd.DataFrame) -> None:
    enc = build_tables(std)["encounters"]
    assert (enc["max_glu_serum"] == "None").sum() >= 1 and enc["max_glu_serum"].notna().all()
    assert enc["a1c_result"].notna().all()


def test_build_tables_is_pure(std: pd.DataFrame) -> None:
    before = std.copy()
    build_tables(std)
    pd.testing.assert_frame_equal(std, before)

