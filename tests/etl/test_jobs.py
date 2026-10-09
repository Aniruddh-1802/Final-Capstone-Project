"""Scheduled jobs: run checks, scan/no-op behaviour, weekly reports, failure path, retry policy, and the DAG files."""
from __future__ import annotations

import ast
import json
import logging
import re
import shutil
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

import check_latest_run
import make_faulty_batch
import scan_incoming
import scheduler
import seed_reference
from app.models import Encounter, PipelineRun, ReportRun
from etl import jobs
from etl.pipeline import run_pipeline
from tests.api.helpers import load_forty

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "mini_diabetic.csv"
DAGS = ROOT / "src" / "airflow" / "dags"


@pytest.fixture()
def db(clean_db: Engine) -> Engine:
    seed_reference.seed_reference(clean_db)
    return clean_db


def add_run(db: Engine, status: str, read=100, loaded=100, rejected=0, skipped=0, error=None, name="f.csv") -> int:
    with Session(db) as s, s.begin():
        run = PipelineRun(source_file=name, file_hash=None, status=status, rows_read=read, rows_loaded=loaded,
                          rows_rejected=rejected, rows_skipped_existing=skipped, error_message=error, triggered_by="test")
        s.add(run)
        s.flush()
        return run.run_id


# ---- check_runs -------------------------------------------------------------------------------------------------
def test_no_new_run_is_a_successful_noop(db: Engine) -> None:
    marker = jobs.max_run_id(db)
    result = jobs.check_runs(db, marker)
    assert result.ok and result.no_op and result.runs == [] and result.problems == []
    assert jobs.summary_lines(result) == ["no new files: nothing to load (successful no-op)"]


def test_clean_run_passes_and_only_runs_after_the_marker_count(db: Engine) -> None:
    add_run(db, "FAILED", error="an OLD failure before this DAG run")
    marker = jobs.max_run_id(db)
    add_run(db, "SUCCESS", read=100, loaded=98, rejected=2)
    result = jobs.check_runs(db, marker)
    assert result.ok and not result.no_op and len(result.runs) == 1 and result.runs[0]["reject_ratio"] == 0.02


def test_failed_run_fails_the_check_with_its_message(db: Engine) -> None:
    marker = jobs.max_run_id(db)
    add_run(db, "FAILED", read=100, loaded=0, rejected=100, error="Batch rejected: reject ratio 0.300", name="bad.csv")
    result = jobs.check_runs(db, marker)
    assert not result.ok and "bad.csv" in result.problems[0] and "Batch rejected" in result.problems[0]


def test_reject_ratio_above_the_limit_fails_but_below_passes(db: Engine) -> None:
    marker = jobs.max_run_id(db)
    add_run(db, "SUCCESS", read=100, loaded=90, rejected=10)  # 10 percent
    assert not jobs.check_runs(db, marker, max_reject_ratio=0.05).ok
    assert jobs.check_runs(db, marker, max_reject_ratio=0.15).ok


def test_non_reconciling_and_still_running_runs_fail(db: Engine) -> None:
    marker = jobs.max_run_id(db)
    add_run(db, "SUCCESS", read=100, loaded=90, rejected=5)  # 95 != 100
    add_run(db, "RUNNING", read=0, loaded=0)
    problems = jobs.check_runs(db, marker).problems
    assert any("does not reconcile" in p for p in problems) and any("still RUNNING" in p for p in problems)


# ---- the scripts ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw, expected", [("17", 17), ("'17'", 17), ('{"new_files": 2, "files": ["a.csv"], "after_run_id": 9}', 9),
                                           ("{'new_files': 0, 'files': [], 'after_run_id': 4}", 4)])
def test_marker_parsing_accepts_the_xcom_line(raw: str, expected: int) -> None:
    assert check_latest_run.parse_marker(raw) == expected


def test_check_script_exit_codes(db: Engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(check_latest_run, "get_engine", lambda: db)
    monkeypatch.setattr(check_latest_run, "configure_logging", lambda: None)
    marker = jobs.max_run_id(db)
    assert check_latest_run.main(["--after-run-id", str(marker)]) == 0  # no new file: success
    add_run(db, "FAILED", error="boom", name="x.csv")
    assert check_latest_run.main(["--after-run-id", str(marker)]) == 1  # a failed run turns the task red
    assert "QUALITY CHECK FAILED" in capsys.readouterr().err
    assert check_latest_run.main(["--after-run-id", str(marker), "--summary"]) == 0  # the summary task never fails


def test_scan_script_prints_one_json_line_with_the_marker(db: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                          capsys: pytest.CaptureFixture[str]) -> None:
    shutil.copy(FIXTURE, tmp_path / "batch_a.csv")
    real = jobs.pending_files
    monkeypatch.setattr(scan_incoming, "get_engine", lambda: db)
    monkeypatch.setattr(scan_incoming, "configure_logging", lambda: None)
    monkeypatch.setattr(scan_incoming.jobs, "pending_files", lambda engine: real(engine, tmp_path))
    add_run(db, "SUCCESS")
    assert scan_incoming.main() == 0
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert json.loads(last) == {"new_files": 1, "files": ["batch_a.csv"], "after_run_id": jobs.max_run_id(db)}


# ---- scan -> load -> check, and the clean no-op on a second run ----------------------------------------------------------
def test_new_file_is_loaded_then_the_next_scan_is_a_noop(db: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shutil.copy(FIXTURE, tmp_path / "encounters_new.csv")
    real = jobs.pending_files
    monkeypatch.setattr(jobs, "pending_files", lambda engine: real(engine, tmp_path))
    first_marker = jobs.max_run_id(db)
    results = jobs.scan_and_load(db)
    assert [(r.status, r.rows_loaded) for r in results] == [("SUCCESS", 30)]
    assert jobs.check_runs(db, first_marker).ok
    second_marker = jobs.max_run_id(db)
    assert jobs.scan_and_load(db) == []  # nothing new
    noop = jobs.check_runs(db, second_marker)
    assert noop.ok and noop.no_op
    with Session(db) as s:
        assert s.scalar(select(func.count()).select_from(Encounter)) == 30  # and nothing was loaded twice


def test_over_threshold_file_fails_the_check_loads_nothing_and_is_quarantined(db: Engine, tmp_path: Path) -> None:
    severe = tmp_path / "severe_faulty_batch.csv"
    corrupted = make_faulty_batch.make_severe(out=severe, share=0.30)
    assert corrupted > 1000
    marker = jobs.max_run_id(db)
    result = run_pipeline(severe, triggered_by="test", engine=db, rejected_dir=tmp_path / "rejected")
    assert result.status == "FAILED" and result.rows_loaded == 0
    with Session(db) as s:
        assert s.scalar(select(func.count()).select_from(Encounter)) == 0  # nothing from the bad file reached the tables
    assert (tmp_path / "rejected" / "severe_faulty_batch_rejected.csv").exists()
    check = jobs.check_runs(db, marker)
    assert not check.ok and "FAILED" in check.problems[0]
    # a retry of the same file fails the same way and leaves another FAILED run, never partial data
    assert run_pipeline(severe, triggered_by="test", engine=db, rejected_dir=tmp_path / "rejected").status == "FAILED"


# ---- weekly reports -------------------------------------------------------------------------------------------------------
def test_weekly_reports_write_four_files_and_four_report_runs(db: Engine, tmp_path: Path) -> None:
    with Session(db) as s, s.begin():
        load_forty(s)
    results = jobs.run_weekly_reports(db, triggered_by="airflow", save_dir=tmp_path)
    assert sorted(f.name.rsplit("_", 2)[0] + "." + f.suffix[1:] for f in tmp_path.iterdir()) == [
        "admissions_trend.csv", "admissions_trend.xlsx", "readmission_summary.csv", "readmission_summary.xlsx"]
    assert len(results) == 4
    with Session(db) as s:
        runs = s.scalars(select(ReportRun)).all()
    assert len(runs) == 4 and {r.triggered_by for r in runs} == {"airflow"}
    csv = next(f for f in tmp_path.iterdir() if f.name.startswith("readmission_summary") and f.suffix == ".csv")
    assert pd.read_csv(csv).groupby("breakdown")["encounters"].sum().eq(39).all()


# ---- fallback scheduler: retry policy -------------------------------------------------------------------------------------
def test_retry_policy_succeeds_after_two_failures_and_gives_up_after_three(caplog: pytest.LogCaptureFixture) -> None:
    calls = []

    def flaky() -> None:
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("transient")
    assert scheduler.with_retries("flaky", flaky, retries=2, delay=0) is True and len(calls) == 3

    always = []
    logging.getLogger("etl.scheduler").propagate = True
    with caplog.at_level(logging.ERROR, logger="etl.scheduler"):
        assert scheduler.with_retries("broken", lambda: always.append(1) or (_ for _ in ()).throw(RuntimeError("down")), retries=2, delay=0) is False
    assert len(always) == 3 and any("JOB FAILURE job=broken after 3 attempts" in r.getMessage() for r in caplog.records)


def test_scheduler_job_raises_when_the_check_finds_a_problem(db: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduler, "get_engine", lambda: db)
    monkeypatch.setattr(jobs, "scan_and_load", lambda engine, triggered_by="scan": add_run(db, "FAILED", error="bad file") and [])
    with pytest.raises(RuntimeError, match="bad file"):
        scheduler.etl_job()


# ---- the DAG files (static: Airflow itself is not installed in the project environment) ---------------------------------------
@pytest.mark.parametrize("name", ["healthcare_incremental_etl.py", "healthcare_weekly_report.py"])
def test_dag_files_compile_and_are_thin(name: str) -> None:
    source = (DAGS / name).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {
        (n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not imported & {"app", "etl", "sqlalchemy", "pandas", "pymysql"}, "DAG files must not import project or database code"
    assert "catchup=False" in source and "retries" in source and "on_failure_callback" in source and "max_active_runs=1" in source
    assert "password" not in source.lower() and "secret" not in source.lower()  # configuration lives in .env, read by the scripts


def test_etl_dag_task_graph_and_schedule() -> None:
    source = (DAGS / "healthcare_incremental_etl.py").read_text(encoding="utf-8")
    assert 'dag_id="healthcare_incremental_etl"' in source and 'schedule="@hourly"' in source
    assert "scan_for_new_files >> run_etl >> check_quality >> record_summary" in source
    assert '"retries": 2' in source and '"retry_delay": RETRY_DELAY' in source and '"HC_RETRY_DELAY_SECONDS", "120"' in source
    assert "PYTHONPATH" not in "".join(l for l in source.splitlines() if not l.lstrip().startswith("#") and "forwarded" not in l)
    for needed in ("scripts/scan_incoming.py", "-m etl.pipeline --scan", "RUN_MODULE", "scripts/check_latest_run.py", "--summary"):
        assert needed in source
    assert re.search(r"xcom_pull\(task_ids=.+scan_for_new_files", source)  # the check receives the marker the scan produced


def test_report_dag_schedule_and_script() -> None:
    source = (DAGS / "healthcare_weekly_report.py").read_text(encoding="utf-8")
    assert 'dag_id="healthcare_weekly_report"' in source and 'schedule="0 6 * * 1"' in source
    assert "scripts/run_weekly_reports.py" in source and "--triggered-by airflow" in source
