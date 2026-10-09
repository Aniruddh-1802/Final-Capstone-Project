"""Schema tests (run against healthcare_test): tables, constraints, seeding."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import seed_reference
import seed_users
from app.models import (
    AppUser, Base, Encounter, EncounterOutcome, Patient, RefAdmissionSource, RefAdmissionType,
    RefDischargeDisposition,
)

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TABLES = {
    "patients", "encounters", "encounter_outcomes", "encounter_diagnoses", "medications",
    "encounter_medications", "ref_admission_type", "ref_admission_source", "ref_discharge_disposition",
    "ref_medical_specialty", "ref_payer", "app_users", "audit_logs", "pipeline_runs", "dq_issues", "report_runs",
}


def _encounter(eid: int, pid: int) -> Encounter:
    return Encounter(
        encounter_id=eid, patient_nbr=pid, admission_date=date(2001, 1, 1), discharge_date=date(2001, 1, 3),
        age_group="[70-80)", age_order=8, admission_type_id=1, discharge_disposition_id=1, admission_source_id=7,
        time_in_hospital=2, num_lab_procedures=10, num_procedures=0, num_medications=5, number_outpatient=0,
        number_emergency=0, number_inpatient=0, number_diagnoses=3, max_glu_serum="None", a1c_result="None",
        med_changed=False, diabetes_med=True,
    )


@pytest.fixture()
def seeded(clean_db: Engine) -> Engine:
    seed_reference.seed_reference(clean_db)
    return clean_db


def test_all_tables_exist(engine: Engine) -> None:
    assert set(inspect(engine).get_table_names()) >= EXPECTED_TABLES
    assert EXPECTED_TABLES == set(Base.metadata.tables)


def test_keys_are_bigint_not_autoincrement(engine: Engine) -> None:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT table_name, column_name, data_type, extra FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND column_name IN ('encounter_id', 'patient_nbr') "
            "AND table_name IN ('patients', 'encounters', 'encounter_outcomes')"
        )).all()
    assert rows
    for table, column, dtype, extra in rows:
        assert dtype == "bigint", f"{table}.{column} is {dtype}"
        assert "auto_increment" not in extra.lower(), f"{table}.{column} must not auto-increment"


def test_enums_defined(engine: Engine) -> None:
    with engine.connect() as conn:
        readmitted = conn.execute(text(
            "SELECT column_type FROM information_schema.columns WHERE table_schema = DATABASE() "
            "AND table_name = 'encounter_outcomes' AND column_name = 'readmitted'")).scalar_one()
    assert readmitted == "enum('NO','>30','<30')"


def test_duplicate_encounter_id_rejected(seeded: Engine) -> None:
    with Session(seeded) as s, s.begin():
        s.add(Patient(patient_nbr=1))
        s.add(_encounter(100, 1))
    with pytest.raises(IntegrityError), Session(seeded) as s, s.begin():
        s.add(_encounter(100, 1))


def test_unknown_patient_rejected_by_mysql(seeded: Engine) -> None:
    with pytest.raises(IntegrityError) as exc, Session(seeded) as s, s.begin():
        s.add(_encounter(200, 999999))
    assert "foreign key" in str(exc.value).lower()


def test_unknown_lookup_id_rejected(seeded: Engine) -> None:
    bad = _encounter(300, 1)
    bad.admission_type_id = 4242
    with Session(seeded) as s, s.begin():
        s.add(Patient(patient_nbr=1))
    with pytest.raises(IntegrityError), Session(seeded) as s, s.begin():
        s.add(bad)


def test_outcome_requires_encounter_and_cascades(seeded: Engine) -> None:
    with Session(seeded) as s, s.begin():
        s.add(Patient(patient_nbr=1))
        s.add(_encounter(400, 1))
        s.add(EncounterOutcome(encounter_id=400, readmitted="<30", readmitted_30d=True,
                               any_readmission=True, is_readmission_eligible=True))
    with pytest.raises(IntegrityError), Session(seeded) as s, s.begin():
        s.add(EncounterOutcome(encounter_id=401, readmitted="NO", readmitted_30d=False,
                               any_readmission=False, is_readmission_eligible=True))
    with seeded.begin() as conn:
        conn.execute(text("DELETE FROM encounters WHERE encounter_id = 400"))
        assert conn.execute(text("SELECT COUNT(*) FROM encounter_outcomes")).scalar_one() == 0


def test_invalid_enum_value_rejected(seeded: Engine) -> None:
    with Session(seeded) as s, s.begin():
        s.add(Patient(patient_nbr=1))
        s.add(_encounter(500, 1))
    with pytest.raises(Exception), seeded.begin() as conn:
        conn.execute(text("SET SESSION sql_mode = 'STRICT_ALL_TABLES'"))
        conn.execute(text("INSERT INTO encounter_outcomes VALUES (500, 'MAYBE', 0, 0, 1)"))


def test_reference_seeding_is_idempotent_and_flags_six_ids(clean_db: Engine) -> None:
    first = seed_reference.seed_reference(clean_db)
    second = seed_reference.seed_reference(clean_db)
    assert first == second == {"admission_type": 8, "admission_source": 25, "discharge_disposition": 30}
    with Session(clean_db) as s:
        flagged = s.scalars(select(RefDischargeDisposition.id).where(
            RefDischargeDisposition.is_expired_or_hospice.is_(True)).order_by(RefDischargeDisposition.id)).all()
        assert flagged == [11, 13, 14, 19, 20, 21]
        assert s.get(RefAdmissionType, 1).description == "Emergency"
        assert s.get(RefAdmissionSource, 1).description == "Physician Referral"  # leading space stripped


def test_user_seeding_hashes_and_is_idempotent(clean_db: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "Admin-Test-Pass-1")
    monkeypatch.delenv("CLINICAL_OPS_PASSWORD", raising=False)
    monkeypatch.delenv("ANALYST_PASSWORD", raising=False)
    generated = seed_users.seed_users(clean_db)
    assert set(generated) == {"clinical_ops", "analyst"}  # admin password came from the environment
    assert seed_users.seed_users(clean_db) == {}  # second run creates nothing
    with Session(clean_db) as s:
        users = s.scalars(select(AppUser).order_by(AppUser.user_id)).all()
    assert sorted(u.role for u in users) == ["administrator", "analyst", "clinical_ops"]
    for u in users:
        assert u.password_hash.startswith("$2") and "Admin-Test-Pass-1" not in u.password_hash


def test_ddl_export_matches_models() -> None:
    from export_ddl import build_ddl  # scripts/ is on the path via conftest pythonpath

    ddl = build_ddl()
    for table in EXPECTED_TABLES:
        assert f"CREATE TABLE {table} (" in ddl
    assert "AUTO_INCREMENT" not in ddl.split("CREATE TABLE encounters")[1].split(";")[0]
