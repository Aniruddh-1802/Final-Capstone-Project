"""Tests for etl.quality: one test per rule on a tiny frame, policy tests, and the faulty-batch integration test."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

from etl import quality as q
from etl.extract import read_batch, read_id_mappings
from etl.transform import standardise_columns

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "mini_diabetic.csv"
REF = q.reference_ids_from_mappings(read_id_mappings(ROOT / "data" / "reference" / "IDs_mapping.csv"))
TODAY = pd.Timestamp("2026-01-01")


@pytest.fixture()
def base() -> pd.DataFrame:
    """The 30 valid fixture rows, standardised; every test mutates its own copy."""
    return standardise_columns(read_batch(FIXTURE))


def fires(rule, df: pd.DataFrame) -> int:
    return int(rule(df, reference_ids=REF, today=TODAY).mask.sum())


def test_clean_fixture_passes_with_only_flags(base: pd.DataFrame) -> None:
    clean, rejected, s = q.validate(base, REF, today=TODAY)
    assert len(clean) == 30 and rejected.empty and s["rows_rejected"] == 0
    assert s["counts_per_rule"]["DQ12"] == 1  # the Unknown/Invalid gender row is flagged, not rejected


def test_dq01_missing_or_non_numeric_ids(base: pd.DataFrame) -> None:
    base = base.astype({"patient_nbr": "float64"})
    base.loc[0, "patient_nbr"] = float("nan")
    base["encounter_id"] = base["encounter_id"].astype(object)
    base.loc[1, "encounter_id"] = "abc"
    assert fires(q.dq01_missing_ids, base) == 2


def test_dq02_duplicate_keeps_first(base: pd.DataFrame) -> None:
    base.loc[5, "encounter_id"] = base.loc[2, "encounter_id"]
    result = q.dq02_duplicate_encounter(base)
    assert result.mask.sum() == 1 and bool(result.mask[5]) and not result.mask[2]


def test_dq03_invalid_reference_codes(base: pd.DataFrame) -> None:
    base.loc[0, "admission_type_id"] = 99
    base.loc[1, "discharge_disposition_id"] = 99
    base.loc[2, "admission_source_id"] = 99
    assert fires(q.dq03_invalid_codes, base) == 3


def test_dq04_invalid_categoricals(base: pd.DataFrame) -> None:
    base.loc[0, "readmitted"] = "MAYBE"
    base.loc[1, "age"] = "[5-15)"
    base.loc[2, "gender"] = "Alien"
    base.loc[3, "metformin"] = "Maybe"
    base.loc[4, "max_glu_serum"] = "high"
    assert fires(q.dq04_invalid_categorical, base) == 5


def test_dq05_numeric_ranges(base: pd.DataFrame) -> None:
    base.loc[0, "time_in_hospital"] = 0
    base.loc[1, "time_in_hospital"] = 15
    base.loc[2, "num_medications"] = -1
    base.loc[3, "number_emergency"] = 9999
    assert fires(q.dq05_numeric_range, base) == 4


def test_dq06_icd_format_corrects_without_rejecting(base: pd.DataFrame) -> None:
    base.loc[0, "diag_1"] = "ABC"
    base.loc[1, "diag_2"] = "1234.5"
    assert fires(q.dq06_icd_format, base) == 2
    clean, rejected, s = q.validate(base, REF, today=TODAY)
    assert rejected.empty and s["corrected_count"] == 2
    assert pd.isna(clean.loc[0, "diag_1"]) and pd.isna(clean.loc[1, "diag_2"])
    valid = standardise_columns(read_batch(FIXTURE))
    valid["diag_1"] = ["V57", "E909", "250.83", "38", "8", "V45.81"] * 5
    assert fires(q.dq06_icd_format, valid) == 0  # V, E, decimal and short source codes are all valid


def test_dq07_missing_or_unparseable_dates(base: pd.DataFrame) -> None:
    base.loc[0, "admission_date"] = None
    base.loc[1, "discharge_date"] = "not-a-date"
    base.loc[2, "admission_date"] = "05/01/2005"  # not ISO
    assert fires(q.dq07_missing_dates, base) == 3


def test_dq08_outside_window_or_future(base: pd.DataFrame) -> None:
    base.loc[0, "admission_date"] = "1998-12-31"
    base.loc[1, "admission_date"] = "2009-01-01"
    base.loc[2, "discharge_date"] = "2009-02-01"
    assert fires(q.dq08_outside_window, base) == 3
    ok = base.copy()
    ok["admission_date"], ok["discharge_date"] = "2008-12-31", "2009-01-10"  # stay running past the window end
    assert fires(q.dq08_outside_window, ok) == 0
    future = q.dq08_outside_window(base, today=pd.Timestamp("2005-01-10")).mask.sum()
    assert future > 3  # most fixture dates are after this 'today'


def test_dq09_discharge_before_admission(base: pd.DataFrame) -> None:
    base.loc[0, "discharge_date"] = "2004-12-30"
    assert fires(q.dq09_discharge_before_admission, base) == 1


def test_dq10_stay_mismatch_only_on_otherwise_valid_rows(base: pd.DataFrame) -> None:
    base.loc[0, "time_in_hospital"] = 5  # dates say 3 days
    base.loc[1, "time_in_hospital"] = -2  # DQ05 territory, not DQ10
    base.loc[2, "discharge_date"] = "2004-01-01"  # DQ09 territory, not DQ10
    assert fires(q.dq10_stay_mismatch, base) == 1


def test_dq11_missing_values_are_a_metric_in_the_summary(base: pd.DataFrame) -> None:
    _, _, s = q.validate(base, REF, today=TODAY)
    assert s["missing_by_column"]["weight"] == 29 and s["missing_by_column"]["diag_3"] == 2
    metrics = [i for i in s["issues"] if i["rule_name"] == "DQ11"]
    assert {"weight", "diag_3", "race"} <= {i["column_name"] for i in metrics}
    assert all(i["action"] == "metric" for i in metrics)


def test_dq12_unknown_gender_flagged_not_removed(base: pd.DataFrame) -> None:
    r = q.dq12_unknown_gender(base)
    assert r.mask.sum() == 1 and r.action == "flagged"
    clean, _, _ = q.validate(base, REF, today=TODAY)
    assert len(clean) == 30


def test_dq13_conflicting_demographics_flagged(base: pd.DataFrame) -> None:
    base.loc[1, "race"] = "Asian"  # patient 1001 now has Caucasian and Asian
    r = q.dq13_conflicting_demographics(base)
    assert r.action == "flagged" and r.mask.sum() >= 2
    clean, _, s = q.validate(base, REF, today=TODAY)
    assert len(clean) == 30 and s["counts_per_rule"]["DQ13"] >= 2


def test_row_failing_two_rules_reported_twice_removed_once(base: pd.DataFrame) -> None:
    base.loc[0, "readmitted"] = "MAYBE"
    base.loc[0, "discharge_disposition_id"] = 99
    clean, rejected, s = q.validate(base, REF, today=TODAY)
    assert s["rows_rejected"] == 1 and len(clean) == 29
    assert sorted(rejected["rule_name"]) == ["DQ03", "DQ04"] and rejected["reason"].str.len().gt(0).all()


def test_file_level_policy_raises_above_threshold(base: pd.DataFrame) -> None:
    base.loc[:9, "readmitted"] = "MAYBE"  # 10 of 30 rows bad = 33%
    with pytest.raises(q.BatchRejectedError) as exc:
        q.validate(base, REF, max_reject_ratio=0.20, today=TODAY)
    assert exc.value.summary["rows_rejected"] == 10 and len(exc.value.rejected) == 10
    clean, rejected, _ = q.validate(base, REF, max_reject_ratio=0.20, today=TODAY, enforce=False)
    assert len(clean) == 20 and len(rejected) == 10
    q.validate(base, REF, max_reject_ratio=0.50, today=TODAY)  # under a looser threshold the file loads


def test_issue_examples_are_capped_but_counts_are_true() -> None:
    big = pd.DataFrame({"encounter_id": range(1, 801)})
    results = [q.RuleResult(pd.Series(True, index=big.index), "DQX", "error", "rejected",
                            pd.Series("col=bad", index=big.index), "x")]
    issues = q.build_dq_issues(big, results, {})
    assert len(issues) == q.MAX_ISSUES_PER_RULE == 500


def test_write_rejected_csv_has_reason(base: pd.DataFrame, tmp_path: Path) -> None:
    base.loc[0, "discharge_disposition_id"] = 99
    _, rejected, _ = q.validate(base, REF, today=TODAY)
    path = q.write_rejected(rejected, "encounters_batch_999.csv", tmp_path)
    assert path is not None and path.name == "encounters_batch_999_rejected.csv"
    written = pd.read_csv(path)
    assert written.loc[0, "rule_name"] == "DQ03" and "discharge_disposition_id=99" in written.loc[0, "reason"]
    assert q.write_rejected(rejected.iloc[0:0], "x.csv", tmp_path) is None


# ---- integration: the generated faulty batch ----------------------------------------------------------------
def _faulty_frame(tmp_path: Path) -> tuple[pd.DataFrame, dict]:
    sys.path.insert(0, str(ROOT / "scripts"))
    import make_faulty_batch as mfb

    source = pd.read_csv(ROOT / "data" / "held_back" / "encounters_batch_003.csv", dtype=str, keep_default_na=False)
    faulty, manifest = mfb.inject_faults(source)
    path = tmp_path / "faulty.csv"
    faulty.to_csv(path, index=False)
    return standardise_columns(read_batch(path)), manifest


def test_faulty_batch_rejects_exactly_the_injected_faults(tmp_path: Path) -> None:
    if not (ROOT / "data" / "held_back" / "encounters_batch_003.csv").exists():
        pytest.skip("run scripts/prepare_batches.py first")
    frame, manifest = _faulty_frame(tmp_path)
    clean, rejected, s = q.validate(frame, REF)
    counts = s["counts_per_rule"]
    inj = manifest["injected"]
    assert counts["DQ01"] == inj["missing_patient_nbr"]["count"] == 3
    assert counts["DQ02"] == inj["duplicate_encounter_id"]["count"] == 5
    assert counts["DQ03"] == inj["unknown_discharge_disposition"]["count"] == 5
    assert counts["DQ05"] == inj["negative_time_in_hospital"]["count"] == 5
    assert counts["DQ09"] == inj["discharge_before_admission"]["count"] == 5
    assert counts["DQ06"] == 5 and s["corrected_count"] == 5  # corrected, not rejected
    for untouched in ("DQ04", "DQ07", "DQ08", "DQ10"):
        assert counts[untouched] == 0
    # Faults were injected on disjoint rows, so no row trips two rules: rows rejected == sum of rejecting rules.
    assert s["rows_rejected"] == manifest["expected_rejected_rows"] == 23 and len(rejected) == 23
    assert s["rows_clean"] == len(frame) - 23
    assert rejected["reason"].str.len().gt(0).all()
    assert clean["diag_1"].isna().sum() >= 5  # the malformed codes were nulled


def test_genuine_held_back_batch_is_clean() -> None:
    path = ROOT / "data" / "held_back" / "encounters_batch_003.csv"
    if not path.exists():
        pytest.skip("run scripts/prepare_batches.py first")
    _, rejected, s = q.validate(standardise_columns(read_batch(path)), REF)
    assert rejected.empty and s["rows_rejected"] == 0


def test_sidecar_matches_generated_file() -> None:
    sidecar = ROOT / "data" / "incoming" / "faulty_batch.json"
    if not sidecar.exists():
        pytest.skip("run scripts/make_faulty_batch.py first")
    assert json.loads(sidecar.read_text())["expected_rejected_rows"] == 23
