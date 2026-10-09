"""Tests for etl.load against healthcare_test."""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

import seed_reference
from app.models import (
    Encounter, EncounterDiagnosis, EncounterMedication, EncounterOutcome, Medication, Patient, RefMedicalSpecialty,
    RefPayer,
)
from etl.extract import read_batch
from etl.load import load_tables, resolve_lookups
from etl.transform import build_tables, standardise_columns

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mini_diabetic.csv"


@pytest.fixture()
def db(clean_db: Engine) -> Engine:
    seed_reference.seed_reference(clean_db)
    return clean_db


@pytest.fixture()
def tables() -> dict:
    return build_tables(standardise_columns(read_batch(FIXTURE)))


def count(engine: Engine, model: type) -> int:
    with Session(engine) as s:
        return s.scalar(select(func.count()).select_from(model))


def test_load_counts_and_second_load_adds_nothing(db: Engine, tables: dict) -> None:
    with db.begin() as conn:
        first = load_tables(conn, tables, "mini")
    assert first["loaded"] == 30 and first["skipped_existing"] == 0
    expected = {Patient: 28, Encounter: 30, EncounterOutcome: 30, EncounterDiagnosis: 86, EncounterMedication: 10}
    assert {m: count(db, m) for m in expected} == expected
    with db.begin() as conn:
        second = load_tables(conn, tables, "mini")
    assert second["loaded"] == 0 and second["skipped_existing"] == 30
    assert {m: count(db, m) for m in expected} == expected


def test_lookups_not_duplicated(db: Engine, tables: dict) -> None:
    with db.begin() as conn:
        resolve_lookups(conn, tables["encounters"])
        resolve_lookups(conn, tables["encounters"])
    specialties = set(tables["encounters"]["medical_specialty"].dropna())
    payers = set(tables["encounters"]["payer_code"].dropna())
    assert count(db, RefMedicalSpecialty) == len(specialties)
    assert count(db, RefPayer) == len(payers)
    with db.begin() as conn:
        load_tables(conn, tables, "mini")
        load_tables(conn, tables, "mini")
    assert count(db, RefMedicalSpecialty) == len(specialties)


def test_missing_specialty_and_payer_stay_null(db: Engine, tables: dict) -> None:
    with db.begin() as conn:
        load_tables(conn, tables, "mini")
        row = conn.execute(text("SELECT specialty_id, payer_id FROM encounters WHERE encounter_id = 7")).one()
    assert row == (None, None)  # encounter 7 has '?' for both


def test_medications_dimension_and_no_rows_for_unprescribed(db: Engine, tables: dict) -> None:
    with db.begin() as conn:
        load_tables(conn, tables, "mini")
        statuses = conn.execute(text("SELECT DISTINCT dosage_status FROM encounter_medications")).scalars().all()
        drugs = set(conn.execute(select(Medication.drug_name)).scalars())
    assert set(statuses) <= {"Steady", "Up", "Down"}
    assert drugs == {"metformin", "insulin", "glyburide", "glipizide", "glyburide_metformin", "glipizide_metformin",
                     "glimepiride_pioglitazone", "metformin_rosiglitazone"}


def test_patient_fill_null_never_overwrites(db: Engine, tables: dict) -> None:
    with Session(db) as s, s.begin():
        s.add(Patient(patient_nbr=1004, race=None, gender="Other-existing"))  # fixture: AfricanAmerican / Female
    with db.begin() as conn:
        counts = load_tables(conn, tables, "mini")
    with Session(db) as s:
        p = s.get(Patient, 1004)
    assert p.race == "AfricanAmerican"  # NULL was filled
    assert p.gender == "Other-existing"  # non-null kept
    assert counts["patients_filled"] == 1 and counts["patients_inserted"] == 27


def test_batch_id_is_recorded(db: Engine, tables: dict) -> None:
    with db.begin() as conn:
        load_tables(conn, tables, "mini_batch")
        assert conn.execute(text("SELECT DISTINCT source_batch_id FROM encounters")).scalars().all() == ["mini_batch"]


def test_chunking_gives_same_result(db: Engine, tables: dict) -> None:
    with db.begin() as conn:
        load_tables(conn, tables, "mini", chunk_size=4)
    assert count(db, Encounter) == 30 and count(db, EncounterDiagnosis) == 86
