"""Load layer: write transformed tables into MySQL with SQLAlchemy Core.

``load_tables`` expects an open Connection inside the caller's transaction and never commits, so every write for
one file succeeds or fails together. Existing keys are pre-selected and skipped; INSERT IGNORE is deliberately not
used because it hides truncation and foreign-key errors.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from typing import Any

import pandas as pd
from sqlalchemy import Connection, bindparam, insert, select, update

from app.models import (
    Encounter, EncounterDiagnosis, EncounterMedication, EncounterOutcome, Medication, Patient, RefMedicalSpecialty,
    RefPayer,
)

log = logging.getLogger(__name__)
DEFAULT_CHUNK_SIZE = 5000


def _chunks(items: list[Any], size: int) -> Iterator[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame -> list of dicts with native Python values and None for missing (PyMySQL cannot bind numpy types)."""
    obj = df.astype(object)
    return obj.where(df.notna(), None).to_dict("records")


def _bulk_insert(conn: Connection, table: Any, rows: list[dict[str, Any]], chunk_size: int) -> int:
    for chunk in _chunks(rows, chunk_size):
        conn.execute(insert(table), chunk)
    return len(rows)


def _existing_values(conn: Connection, column: Any, values: list[Any], chunk_size: int) -> set[Any]:
    found: set[Any] = set()
    for chunk in _chunks(values, chunk_size):
        found.update(conn.execute(select(column).where(column.in_(chunk))).scalars())
    return found


def ensure_lookup(conn: Connection, table: Any, key_col: str, id_col: str, values: Iterable[Any]) -> dict[str, int]:
    """Insert the distinct non-null values that are missing from a lookup table and return ``{value: id}``."""
    wanted = sorted({str(v) for v in values if pd.notna(v)})
    if not wanted:
        return {}
    key, pk = table.c[key_col], table.c[id_col]
    known = dict(conn.execute(select(key, pk).where(key.in_(wanted))).all())
    missing = [v for v in wanted if v not in known]
    if missing:
        conn.execute(insert(table), [{key_col: v} for v in missing])
        known = dict(conn.execute(select(key, pk).where(key.in_(wanted))).all())
    return known


def resolve_lookups(conn: Connection, encounters: pd.DataFrame) -> dict[str, dict[str, int]]:
    """Upsert distinct medical_specialty / payer_code values into their ref tables; return the id maps.

    Missing values stay NULL (they are simply absent from the maps).
    """
    maps = {
        "specialty": ensure_lookup(conn, RefMedicalSpecialty.__table__, "name", "specialty_id",
                                    encounters["medical_specialty"].dropna().unique()),
        "payer": ensure_lookup(conn, RefPayer.__table__, "payer_code", "payer_id",
                                encounters["payer_code"].dropna().unique()),
    }
    log.info("Lookups resolved: %d specialties, %d payers", len(maps["specialty"]), len(maps["payer"]))
    return maps


def _load_patients(conn: Connection, patients: pd.DataFrame, chunk_size: int) -> tuple[int, int]:
    """Insert new patients; fill NULL race/gender on existing ones without ever overwriting a non-null value."""
    table = Patient.__table__
    ids = [int(i) for i in patients["patient_nbr"]]
    existing: dict[int, tuple[Any, Any]] = {}
    for chunk in _chunks(ids, chunk_size):
        existing.update({r[0]: (r[1], r[2]) for r in conn.execute(
            select(table.c.patient_nbr, table.c.race, table.c.gender).where(table.c.patient_nbr.in_(chunk)))})
    new_rows = [r for r in _records(patients) if r["patient_nbr"] not in existing]
    _bulk_insert(conn, table, new_rows, chunk_size)
    fills = {"race": [], "gender": []}
    for row in _records(patients):
        current = existing.get(row["patient_nbr"])
        if current is None:
            continue
        for idx, col in enumerate(("race", "gender")):
            if current[idx] is None and row[col] is not None:
                fills[col].append({"p": row["patient_nbr"], "v": row[col]})
    for col, params in fills.items():
        if params:
            conn.execute(update(table).where(table.c.patient_nbr == bindparam("p")).values({col: bindparam("v")}),
                         params)
    filled = len(fills["race"]) + len(fills["gender"])
    log.info("Patients: %d inserted, %d NULL fields filled", len(new_rows), filled)
    return len(new_rows), filled


def _encounter_rows(encounters: pd.DataFrame, maps: dict[str, dict[str, int]], batch_id: str) -> list[dict[str, Any]]:
    out = encounters.copy()
    out["specialty_id"] = out["medical_specialty"].map(maps["specialty"]).astype("Int64")
    out["payer_id"] = out["payer_code"].map(maps["payer"]).astype("Int64")
    out["source_batch_id"] = batch_id
    return _records(out.drop(columns=["medical_specialty", "payer_code"]))


def _load_medications(conn: Connection, meds: pd.DataFrame, chunk_size: int) -> int:
    ids = ensure_lookup(conn, Medication.__table__, "drug_name", "medication_id", meds["drug_name"].unique())
    rows = meds.assign(medication_id=meds["drug_name"].map(ids)).drop(columns="drug_name")
    return _bulk_insert(conn, EncounterMedication.__table__, _records(rows), chunk_size)


def load_tables(conn: Connection, tables: dict[str, Any], batch_id: str,
                chunk_size: int = DEFAULT_CHUNK_SIZE) -> dict[str, int]:
    """Insert the tables from ``etl.transform.build_tables`` in dependency order inside the caller's transaction.

    Encounters whose id already exists (soft-deleted ones included) are skipped together with their child rows.
    Returns ``loaded`` (new encounters), ``skipped_existing`` and per-table insert counts.
    """
    enc: pd.DataFrame = tables["encounters"]
    ids = [int(i) for i in enc["encounter_id"]]
    existing = _existing_values(conn, Encounter.__table__.c.encounter_id, ids, chunk_size)
    keep = ~enc["encounter_id"].isin(existing)
    new_enc = enc[keep]
    counts = {"loaded": len(new_enc), "skipped_existing": int((~keep).sum())}
    if new_enc.empty:
        log.info("No new encounters in %s: %d skipped as existing", batch_id, counts["skipped_existing"])
        return counts | {"patients_inserted": 0, "patients_filled": 0, "outcomes": 0, "diagnoses": 0, "medications": 0}

    new_ids = set(new_enc["encounter_id"])
    patients = tables["patients"]
    patients = patients[patients["patient_nbr"].isin(set(new_enc["patient_nbr"]))]
    counts["patients_inserted"], counts["patients_filled"] = _load_patients(conn, patients, chunk_size)
    maps = resolve_lookups(conn, new_enc)
    _bulk_insert(conn, Encounter.__table__, _encounter_rows(new_enc, maps, batch_id), chunk_size)
    outcomes = tables["outcomes"]
    counts["outcomes"] = _bulk_insert(conn, EncounterOutcome.__table__,
                                      _records(outcomes[outcomes["encounter_id"].isin(new_ids)]), chunk_size)
    diag = tables["diagnoses"]
    counts["diagnoses"] = _bulk_insert(conn, EncounterDiagnosis.__table__,
                                       _records(diag[diag["encounter_id"].isin(new_ids)]), chunk_size)
    meds = tables["encounter_medications"]
    counts["medications"] = _load_medications(conn, meds[meds["encounter_id"].isin(new_ids)], chunk_size)
    log.info("Loaded %s: %s", batch_id, counts)
    return counts

