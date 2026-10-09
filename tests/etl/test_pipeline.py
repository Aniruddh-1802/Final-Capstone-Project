"""Tests for etl.pipeline and etl.incremental against healthcare_test."""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

import seed_reference
from app.models import DqIssue, Encounter, EncounterOutcome, PipelineRun
from etl import load as load_module
from etl.incremental import find_new_files, sha256_file
from etl.pipeline import run_pipeline

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mini_diabetic.csv"


@pytest.fixture()
def db(clean_db: Engine) -> Engine:
    seed_reference.seed_reference(clean_db)
    return clean_db


def run(db: Engine, path: Path, tmp_path: Path, **kw):
    return run_pipeline(path, triggered_by="test", engine=db, rejected_dir=tmp_path / "rejected", **kw)


def n(db: Engine, model: type) -> int:
    with Session(db) as s:
        return s.scalar(select(func.count()).select_from(model))


def reversed_copy(tmp_path: Path, name: str = "reordered.csv") -> Path:
    df = pd.read_csv(FIXTURE, dtype=str, keep_default_na=False).iloc[::-1]
    target = tmp_path / name
    df.to_csv(target, index=False)
    return target


def test_pipeline_stage_logs_reach_the_log_file(tmp_path: Path) -> None:
    """Regression: the CLI once configured a logger named 'pipeline', so no etl.* record ever reached a file."""
    import logging

    from etl.pipeline import configure_logging

    logger = logging.getLogger("etl")
    for handler in list(logger.handlers):  # start clean so the test controls where the file goes
        logger.removeHandler(handler)
        handler.close()
    configure_logging(tmp_path)
    logging.getLogger("etl.pipeline").info("stage=extract duration=0.01s")
    logging.getLogger("etl.load").info("Loaded batch")
    for handler in logger.handlers:
        handler.flush()
    text = (tmp_path / "etl.log").read_text(encoding="utf-8")
    assert "stage=extract" in text and "Loaded batch" in text
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def test_first_run_loads_and_reconciles(db: Engine, tmp_path: Path) -> None:
    r = run(db, FIXTURE, tmp_path)
    assert (r.status, r.rows_read, r.rows_loaded, r.rows_rejected, r.rows_skipped_existing) == ("SUCCESS", 30, 30, 0, 0)
    assert n(db, Encounter) == n(db, EncounterOutcome) == 30
    with Session(db) as s:
        row = s.scalar(select(PipelineRun).where(PipelineRun.run_id == r.run_id))
    assert row.status == "SUCCESS" and row.finished_at is not None and row.file_hash == sha256_file(FIXTURE)
    assert row.rows_read == row.rows_loaded + row.rows_rejected + row.rows_skipped_existing
    assert row.dq_summary_json["rows_in"] == 30 and row.triggered_by == "test"


def test_interrupted_run_is_closed_as_failed_on_the_next_attempt(db: Engine, tmp_path: Path) -> None:
    """A hard-killed process leaves a RUNNING row; the next run of the same file must close it, not ignore it."""
    from sqlalchemy import insert
    with db.begin() as conn:
        conn.execute(insert(PipelineRun).values(source_file=FIXTURE.name, file_hash=sha256_file(FIXTURE),
                                                status="RUNNING", triggered_by="killed"))
        conn.execute(insert(PipelineRun).values(source_file="other.csv", file_hash="f" * 64,
                                                status="RUNNING", triggered_by="other"))
    r = run(db, FIXTURE, tmp_path)
    assert r.status == "SUCCESS" and n(db, Encounter) == 30
    with Session(db) as s:
        rows = {x.triggered_by: x for x in s.scalars(select(PipelineRun))}
    assert rows["killed"].status == "FAILED" and "Interrupted" in rows["killed"].error_message
    assert rows["killed"].finished_at is not None
    assert rows["other"].status == "RUNNING"  # runs of other files are never touched


def test_same_file_twice_is_skipped_duplicate(db: Engine, tmp_path: Path) -> None:
    run(db, FIXTURE, tmp_path)
    r = run(db, FIXTURE, tmp_path)
    assert r.status == "SKIPPED_DUPLICATE_FILE" and r.rows_loaded == 0
    assert n(db, Encounter) == 30 and n(db, PipelineRun) == 2


def test_renamed_reordered_copy_skips_all_rows(db: Engine, tmp_path: Path) -> None:
    run(db, FIXTURE, tmp_path)
    copy = reversed_copy(tmp_path)
    assert sha256_file(copy) != sha256_file(FIXTURE)  # different bytes -> the file hash cannot catch it
    r = run(db, copy, tmp_path)
    assert (r.status, r.rows_loaded, r.rows_skipped_existing, r.rows_read) == ("SUCCESS", 0, 30, 30)
    assert n(db, Encounter) == 30


def test_forced_failure_mid_load_leaves_nothing(db: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("forced failure after encounters were inserted")
    monkeypatch.setattr(load_module, "_load_medications", boom)
    r = run(db, FIXTURE, tmp_path)
    assert r.status == "FAILED" and "forced failure" in r.error_message
    for model in (Encounter, EncounterOutcome):
        assert n(db, model) == 0
    with db.connect() as conn:
        for table in ("patients", "encounter_diagnoses", "encounter_medications", "medications"):
            assert conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0
    monkeypatch.undo()
    assert run(db, FIXTURE, tmp_path).status == "SUCCESS"  # a failed run is not 'done': the same file loads next time


def test_reconciliation_failure_rolls_back(db: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = load_module.load_tables

    def lying(conn, tables, batch_id, chunk_size=5000):
        counts = real(conn, tables, batch_id, chunk_size)
        counts["loaded"] -= 1  # claims one row fewer than it inserted
        return counts
    monkeypatch.setattr("etl.pipeline.load_tables", lying)
    r = run(db, FIXTURE, tmp_path)
    assert r.status == "FAILED" and "ReconciliationError" in r.error_message
    assert n(db, Encounter) == 0


def test_threshold_failure_loads_nothing_and_records_issues(db: Engine, tmp_path: Path) -> None:
    df = pd.read_csv(FIXTURE, dtype=str, keep_default_na=False)
    df.loc[:9, "readmitted"] = "MAYBE"  # 10/30 = 33% > 20%
    bad = tmp_path / "bad.csv"
    df.to_csv(bad, index=False)
    r = run(db, bad, tmp_path)
    assert r.status == "FAILED" and "Batch rejected" in r.error_message
    assert (r.rows_loaded, r.rows_rejected, r.rows_read) == (0, 30, 30)  # whole file refused
    assert n(db, Encounter) == 0
    assert (tmp_path / "rejected" / "bad_rejected.csv").exists()
    with Session(db) as s:
        run_row = s.scalar(select(PipelineRun).where(PipelineRun.run_id == r.run_id))
        rules = set(s.scalars(select(DqIssue.rule_name).where(DqIssue.run_id == r.run_id)))
    assert run_row.dq_summary_json["rows_failing_rules"] == 10 and "DQ04" in rules


def test_row_level_rejects_quarantined_and_clean_rows_load(db: Engine, tmp_path: Path) -> None:
    df = pd.read_csv(FIXTURE, dtype=str, keep_default_na=False)
    df.loc[0, "discharge_disposition_id"] = "99"
    df.loc[1, "time_in_hospital"] = "-1"
    f = tmp_path / "some_bad.csv"
    df.to_csv(f, index=False)
    r = run(db, f, tmp_path)
    assert (r.status, r.rows_read, r.rows_loaded, r.rows_rejected) == ("SUCCESS", 30, 28, 2)
    rejected = pd.read_csv(tmp_path / "rejected" / "some_bad_rejected.csv")
    assert sorted(rejected["rule_name"]) == ["DQ03", "DQ05"] and rejected["reason"].notna().all()
    with Session(db) as s:
        kinds = set(s.execute(select(DqIssue.rule_name, DqIssue.action).where(DqIssue.run_id == r.run_id)).all())
    assert ("DQ03", "rejected") in kinds and ("DQ11", "metric") in kinds


def test_missing_columns_fail_run_cleanly(db: Engine, tmp_path: Path) -> None:
    f = tmp_path / "narrow.csv"
    f.write_text("encounter_id,patient_nbr\n1,2\n", encoding="utf-8")
    r = run(db, f, tmp_path)
    assert r.status == "FAILED" and "MissingColumnsError" in r.error_message and n(db, Encounter) == 0


def test_unseeded_reference_tables_fail_clearly(clean_db: Engine, tmp_path: Path) -> None:
    r = run(clean_db, FIXTURE, tmp_path)
    assert r.status == "FAILED" and "ReferenceDataError" in r.error_message


def test_find_new_files_orders_by_name_and_skips_loaded(db: Engine, tmp_path: Path) -> None:
    inc = tmp_path / "incoming"
    inc.mkdir()
    shutil.copy(FIXTURE, inc / "b_second.csv")
    reversed_copy(inc, "a_first.csv")
    (inc / "notes.txt").write_text("ignore me")
    with db.connect() as conn:
        assert [p.name for p in find_new_files(inc, conn)] == ["a_first.csv", "b_second.csv"]
    run(db, inc / "a_first.csv", tmp_path)
    with db.connect() as conn:
        assert [p.name for p in find_new_files(inc, conn)] == ["b_second.csv"]
