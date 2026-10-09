"""Analytics computed in SQL (SQLAlchemy func/case) over v_active_encounters - the same definitions as db/queries.

Numerator of every rate: active, eligible encounters with readmitted_30d. Denominator: eligible encounters.
Volumes (encounters, average length of stay) count all active encounters. Group queries never join diagnoses, and the
drug query joins a table whose key is (encounter_id, medication_id), so no encounter is counted twice; tests assert
that group counts add up to the filtered total. No race or gender is ever selected.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import ColumnElement, Numeric, Select, String, and_, case, cast, func, literal_column, select
from sqlalchemy.orm import Session

from app.models import EncounterMedication, Medication
from app.schemas.analytics import DENOMINATOR
from app.services.query_helpers import check_date_range, inclusive_day_range
from app.services.views import V

SMALL_N = 11
ELIGIBLE = V.c.is_readmission_eligible.is_(True)
ENCOUNTERS = func.count().label("encounters")
ELIGIBLE_N = func.coalesce(func.sum(case((ELIGIBLE, 1), else_=0)), 0).label("eligible_encounters")
R30_N = func.coalesce(func.sum(case((and_(ELIGIBLE, V.c.readmitted_30d.is_(True)), 1), else_=0)), 0).label("readmitted_30d")
ANY_N = func.coalesce(func.sum(case((and_(ELIGIBLE, V.c.any_readmission.is_(True)), 1), else_=0)), 0).label("any_readmitted")
AVG_LOS = func.avg(cast(V.c.time_in_hospital, Numeric(12, 6))).label("avg_length_of_stay")  # cast: MySQL AVG(int) keeps only 4 decimals

# group_by name -> (id column or None, label column, ordering)
_SPECIALTY = func.coalesce(V.c.medical_specialty, "Unknown")
_MONTH = func.date_format(V.c.admission_date, "%Y-%m")
DIMENSIONS: dict[str, tuple[ColumnElement[Any] | None, ColumnElement[Any], str]] = {
    "age_group": (V.c.age_order, V.c.age_group, "id"),
    "admission_type": (V.c.admission_type_id, V.c.admission_type, "volume"),
    "admission_source": (V.c.admission_source_id, V.c.admission_source, "volume"),
    "discharge_disposition": (V.c.discharge_disposition_id, V.c.discharge_disposition, "volume"),
    "specialty": (None, _SPECIALTY, "volume"),
    "month": (None, _MONTH, "label"),
    "overall": (None, literal_column("'All encounters'"), "label"),  # one group: the whole filtered population
}


def filter_conditions(f: dict[str, Any]) -> list[ColumnElement[bool]]:
    """Shared filters (date_from, date_to, age_group, admission_type_id) as WHERE conditions."""
    check_date_range(f.get("date_from"), f.get("date_to"))
    conditions = inclusive_day_range(V.c.admission_date, f.get("date_from"), f.get("date_to"))
    if f.get("age_group"):
        conditions.append(V.c.age_group == f["age_group"])
    if f.get("admission_type_id") is not None:
        conditions.append(V.c.admission_type_id == f["admission_type_id"])
    return conditions


def meta(filters: dict[str, Any]) -> dict[str, Any]:
    """Response metadata: applied filters, the denominator in words, the simulated-dates notice, a timestamp."""
    applied = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in filters.items() if v is not None}
    return {"filters": applied, "denominator": DENOMINATOR, "dates_simulated": True,
            "generated_at": datetime.now().replace(microsecond=0)}


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _float(value: Any) -> float | None:
    return None if value is None else round(float(value), 6)


def _group_row(row: Any, label: str | None = None) -> dict[str, Any]:
    m = row._mapping
    enc, elig, r30 = int(m["encounters"]), int(m["eligible_encounters"]), int(m["readmitted_30d"])
    return {"id": m.get("id"), "label": str(label if label is not None else m["label"]), "encounters": enc,
            "eligible_encounters": elig, "readmitted_30d": r30, "readmission_rate": _rate(r30, elig),
            "small_n": enc < SMALL_N, "avg_length_of_stay": _float(m.get("avg_length_of_stay"))}


def _where(stmt: Select[Any], conditions: list[ColumnElement[bool]]) -> Select[Any]:
    return stmt.where(*conditions) if conditions else stmt


def summary(session: Session, f: dict[str, Any]) -> dict[str, Any]:
    """Headline KPIs for the filtered active encounters."""
    stmt = _where(select(ENCOUNTERS, func.count(func.distinct(V.c.patient_nbr)).label("unique_patients"), AVG_LOS,
                         func.avg(cast(V.c.num_medications, Numeric(12, 6))).label("avg_num_medications"), ELIGIBLE_N, R30_N, ANY_N),
                  filter_conditions(f))
    m = session.execute(stmt).one()._mapping
    elig = int(m["eligible_encounters"])
    return {"total_encounters": int(m["encounters"]), "unique_patients": int(m["unique_patients"]),
            "avg_length_of_stay": _float(m["avg_length_of_stay"]), "avg_num_medications": _float(m["avg_num_medications"]),
            "eligible_encounters": elig, "readmitted_30d": int(m["readmitted_30d"]),
            "readmission_rate_30d": _rate(int(m["readmitted_30d"]), elig),
            "any_readmission_rate": _rate(int(m["any_readmitted"]), elig)}


def _grouped(session: Session, id_col: ColumnElement[Any] | None, label: ColumnElement[Any], order: str,
             f: dict[str, Any], extra_where: list[ColumnElement[bool]] | None = None) -> list[dict[str, Any]]:
    cols = [label.label("label"), ENCOUNTERS, AVG_LOS, ELIGIBLE_N, R30_N]
    group = [label]
    if id_col is not None:
        cols.insert(0, id_col.label("id"))
        group.insert(0, id_col)
    stmt = _where(select(*cols), filter_conditions(f) + (extra_where or [])).group_by(*group)
    if order == "id" and id_col is not None:
        stmt = stmt.order_by(id_col)
    elif order == "label":
        stmt = stmt.order_by(label)
    else:
        stmt = stmt.order_by(func.count().desc(), label)
    return [_group_row(r) for r in session.execute(stmt)]


def readmissions(session: Session, group_by: str, f: dict[str, Any]) -> list[dict[str, Any]]:
    """Encounters and 30-day readmission rate per group (age by age_order, month chronologically, others by volume)."""
    id_col, label, order = DIMENSIONS[group_by]
    return _grouped(session, id_col, label, order, f)


def admissions_trend(session: Session, granularity: str, f: dict[str, Any]) -> list[dict[str, Any]]:
    """Per month or per year; periods without encounters are omitted (never zero-filled with a misleading rate)."""
    label = _MONTH if granularity == "month" else cast(func.year(V.c.admission_date), String)
    return _grouped(session, None, label, "label", f)


def length_of_stay(session: Session, group_by: str, f: dict[str, Any]) -> list[dict[str, Any]]:
    """Average, min, max and a 14-bucket histogram of length of stay per group."""
    id_col, label, order = DIMENSIONS[group_by]
    buckets = [func.coalesce(func.sum(case((V.c.time_in_hospital == d, 1), else_=0)), 0).label(f"d{d}") for d in range(1, 15)]
    cols = [label.label("label"), ENCOUNTERS, AVG_LOS, func.min(V.c.time_in_hospital).label("min_los"),
            func.max(V.c.time_in_hospital).label("max_los"), *buckets]
    group = [label]
    if id_col is not None:
        cols.insert(0, id_col.label("id"))
        group.insert(0, id_col)
    stmt = _where(select(*cols), filter_conditions(f)).group_by(*group)
    stmt = stmt.order_by(id_col) if order == "id" and id_col is not None else (
        stmt.order_by(label) if order == "label" else stmt.order_by(func.count().desc(), label))
    out = []
    for r in session.execute(stmt):
        m = r._mapping
        out.append({"id": m.get("id"), "label": str(m["label"]), "encounters": int(m["encounters"]),
                    "avg_length_of_stay": _float(m["avg_length_of_stay"]), "min_length_of_stay": m["min_los"],
                    "max_length_of_stay": m["max_los"], "histogram": [int(m[f"d{d}"]) for d in range(1, 15)],
                    "small_n": int(m["encounters"]) < SMALL_N})
    return out


def medications(session: Session, f: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Top 10 drugs by use, insulin dosage status (No = not prescribed) and A1C result, each with the 30-day rate."""
    top = (_where(select(Medication.drug_name.label("label"), ENCOUNTERS, AVG_LOS, ELIGIBLE_N, R30_N), filter_conditions(f))
           .select_from(V).join(EncounterMedication, EncounterMedication.encounter_id == V.c.encounter_id)
           .join(Medication, Medication.medication_id == EncounterMedication.medication_id)
           .group_by(Medication.drug_name).order_by(func.count().desc(), Medication.drug_name).limit(10))
    insulin = (select(EncounterMedication.encounter_id.label("eid"), EncounterMedication.dosage_status.label("status"))
               .join(Medication, Medication.medication_id == EncounterMedication.medication_id)
               .where(Medication.drug_name == "insulin").subquery())
    status = func.coalesce(insulin.c.status, "No", type_=String)  # type_: the Enum type would reject the value 'No'
    ins =(_where(select(status.label("label"), ENCOUNTERS, AVG_LOS, ELIGIBLE_N, R30_N), filter_conditions(f))
           .select_from(V).outerjoin(insulin, insulin.c.eid == V.c.encounter_id).group_by(status))
    a1c_order = case((V.c.a1c_result == "None", 0), (V.c.a1c_result == "Norm", 1), (V.c.a1c_result == ">7", 2), else_=3)
    a1c = (_where(select(V.c.a1c_result.label("label"), ENCOUNTERS, AVG_LOS, ELIGIBLE_N, R30_N), filter_conditions(f))
           .group_by(V.c.a1c_result).order_by(a1c_order))
    return {"top_drugs": [_group_row(r) for r in session.execute(top)],
            "insulin_status": sorted((_group_row(r) for r in session.execute(ins)),
                                     key=lambda g: ("No", "Steady", "Up", "Down").index(g["label"])),
            "a1c_result": [_group_row(r) for r in session.execute(a1c)]}


def utilization(session: Session, f: dict[str, Any]) -> list[dict[str, Any]]:
    """Prior inpatient visits bucket (0, 1, 2, 3+) versus the 30-day readmission rate."""
    bucket = case((V.c.number_inpatient >= 3, "3+"), else_=cast(V.c.number_inpatient, String))
    stmt = _where(select(bucket.label("label"), ENCOUNTERS, AVG_LOS, ELIGIBLE_N, R30_N), filter_conditions(f)
                  ).group_by(bucket).order_by(bucket)
    return [_group_row(r) for r in session.execute(stmt)]



