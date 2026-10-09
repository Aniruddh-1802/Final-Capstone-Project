"""Encounter business logic: validated CRUD with server-derived flags, audit in the same transaction, and filtered lists.

Reads go through the ``v_active_encounters`` view (single soft-delete filter). Writes use the ORM and check that the
encounter and its patient are active. readmitted_30d, any_readmission and is_readmission_eligible are always computed
here from ``readmitted`` and ``discharge_disposition_id``; anything the client sends for them is ignored.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy import delete, exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import (
    Encounter, EncounterDiagnosis, EncounterMedication, EncounterOutcome, Medication, Patient, RefAdmissionSource,
    RefAdmissionType, RefDischargeDisposition, RefMedicalSpecialty, RefPayer,
)
from app.permissions import is_minimised
from app.schemas.encounters import EncounterCreate, EncounterUpdate, content_problems, stay_problems
from app.services import audit
from app.services.audit import AuditContext
from app.services.query_helpers import (
    PageParams, SortSpec, apply_filters, apply_sort, check_date_range, inclusive_day_range, paginate, validation_error,
)
from app.services.views import V
from etl.load import ensure_lookup
from etl.transform import AGE_ORDER, EXPIRED_OR_HOSPICE_IDS

log = logging.getLogger(__name__)
ENCOUNTER_SORT = SortSpec(
    columns={"encounter_id": V.c.encounter_id, "admission_date": V.c.admission_date,
             "time_in_hospital": V.c.time_in_hospital, "num_medications": V.c.num_medications,
             "number_inpatient": V.c.number_inpatient, "age_order": V.c.age_order},
    default="admission_date", tiebreaker=V.c.encounter_id)
MINIMISED_DROP = ("patient_nbr", "source_batch_id")
_ICD_PREFIX = re.compile(r"^[A-Za-z0-9.]{1,10}$")
_SCALARS = ("admission_date", "discharge_date", "age_group", "admission_type_id", "discharge_disposition_id",
            "admission_source_id", "time_in_hospital", "num_lab_procedures", "num_procedures", "num_medications",
            "number_outpatient", "number_emergency", "number_inpatient", "number_diagnoses", "max_glu_serum",
            "a1c_result", "med_changed", "diabetes_med")


def derive_flags(readmitted: str, discharge_disposition_id: int) -> dict[str, bool]:
    """The one server-side definition of the outcome flags (matches etl.transform.derive_outcome_flags)."""
    return {"readmitted_30d": readmitted == "<30", "any_readmission": readmitted in ("<30", ">30"),
            "is_readmission_eligible": discharge_disposition_id not in EXPIRED_OR_HOSPICE_IDS}


def _not_found(encounter_id: int) -> ApiError:
    return ApiError(404, "not_found", f"Encounter {encounter_id} not found")


def _errors(problems: list[tuple[str, str]]) -> ApiError:
    return ApiError(422, "validation_error", "Request validation failed",
                    [{"loc": ["body", f], "msg": m, "type": "value_error"} for f, m in problems])


def _check_lookups(session: Session, admission_type_id: int, discharge_disposition_id: int,
                   admission_source_id: int) -> list[tuple[str, str]]:
    problems = []
    for field, model, value in (("admission_type_id", RefAdmissionType, admission_type_id),
                                ("discharge_disposition_id", RefDischargeDisposition, discharge_disposition_id),
                                ("admission_source_id", RefAdmissionSource, admission_source_id)):
        if session.get(model, value) is None:
            problems.append((field, f"{field} {value} does not exist in the reference table"))
    return problems


def _resolve_lookup_ids(session: Session, specialty: str | None, payer: str | None) -> tuple[int | None, int | None]:
    conn = session.connection()
    spec = ensure_lookup(conn, RefMedicalSpecialty.__table__, "name", "specialty_id", [specialty]) if specialty else {}
    pay = ensure_lookup(conn, RefPayer.__table__, "payer_code", "payer_id", [payer]) if payer else {}
    return spec.get(specialty or ""), pay.get(payer or "")


def snapshot(session: Session, enc: Encounter) -> dict[str, Any]:
    """Full audit/response state of an encounter (without timestamps): fields, outcome flags, diagnoses, medications."""
    session.flush()
    outcome = session.get(EncounterOutcome, enc.encounter_id)
    spec = session.get(RefMedicalSpecialty, enc.specialty_id) if enc.specialty_id else None
    pay = session.get(RefPayer, enc.payer_id) if enc.payer_id else None
    diag = session.execute(select(EncounterDiagnosis.position, EncounterDiagnosis.icd9_code).where(
        EncounterDiagnosis.encounter_id == enc.encounter_id).order_by(EncounterDiagnosis.position)).all()
    meds = session.execute(select(Medication.drug_name, EncounterMedication.dosage_status).join(
        EncounterMedication, EncounterMedication.medication_id == Medication.medication_id).where(
        EncounterMedication.encounter_id == enc.encounter_id).order_by(Medication.drug_name)).all()
    snap: dict[str, Any] = {"encounter_id": enc.encounter_id, "patient_nbr": enc.patient_nbr,
                            **{f: getattr(enc, f) for f in _SCALARS}, "age_order": enc.age_order,
                            "medical_specialty": spec.name if spec else None, "payer_code": pay.payer_code if pay else None,
                            "is_deleted": bool(enc.is_deleted)}
    if outcome is not None:
        snap.update(readmitted=outcome.readmitted, readmitted_30d=bool(outcome.readmitted_30d),
                    any_readmission=bool(outcome.any_readmission),
                    is_readmission_eligible=bool(outcome.is_readmission_eligible))
    snap["diagnoses"] = [{"position": p, "icd9_code": c} for p, c in diag]
    snap["medications"] = [{"drug_name": n, "dosage_status": s} for n, s in meds]
    return snap


def _replace_children(session: Session, encounter_id: int, diagnoses: list[Any] | None,
                      medications: list[Any] | None) -> None:
    if diagnoses is not None:
        session.execute(delete(EncounterDiagnosis).where(EncounterDiagnosis.encounter_id == encounter_id))
        session.add_all(EncounterDiagnosis(encounter_id=encounter_id, position=d.position, icd9_code=d.icd9_code)
                        for d in diagnoses)
    if medications is not None:
        session.execute(delete(EncounterMedication).where(EncounterMedication.encounter_id == encounter_id))
        if medications:
            ids = ensure_lookup(session.connection(), Medication.__table__, "drug_name", "medication_id",
                                [m.drug_name for m in medications])
            session.add_all(EncounterMedication(encounter_id=encounter_id, medication_id=ids[m.drug_name],
                                                dosage_status=m.dosage_status) for m in medications)
    session.flush()


def _active_encounter(session: Session, encounter_id: int) -> Encounter:
    """The ORM encounter for a write, or 404 when it (or its patient) is missing or soft-deleted."""
    enc = session.get(Encounter, encounter_id)
    patient = session.get(Patient, enc.patient_nbr) if enc else None
    if enc is None or enc.is_deleted or patient is None or patient.is_deleted:
        raise _not_found(encounter_id)
    return enc


def create(session: Session, ctx: AuditContext, data: EncounterCreate) -> int:
    """Validate, insert encounter + outcome + children, audit CREATE, commit once. Returns the encounter id."""
    if session.get(Encounter, data.encounter_id) is not None:
        raise ApiError(409, "conflict", f"Encounter {data.encounter_id} already exists")
    problems = stay_problems(data.admission_date, data.discharge_date, data.time_in_hospital)
    problems += content_problems(data.diagnoses, data.medications)
    problems += _check_lookups(session, data.admission_type_id, data.discharge_disposition_id, data.admission_source_id)
    patient = session.get(Patient, data.patient_nbr)
    if patient is None or patient.is_deleted:
        problems.append(("patient_nbr", f"patient {data.patient_nbr} does not exist"))
    if problems:
        raise _errors(problems)
    specialty_id, payer_id = _resolve_lookup_ids(session, data.medical_specialty, data.payer_code)
    enc = Encounter(encounter_id=data.encounter_id, patient_nbr=data.patient_nbr, specialty_id=specialty_id,
                    payer_id=payer_id, age_order=AGE_ORDER[data.age_group], **{f: getattr(data, f) for f in _SCALARS})
    session.add(enc)
    flags = derive_flags(data.readmitted, data.discharge_disposition_id)  # never taken from the request
    try:
        session.flush()
        session.add(EncounterOutcome(encounter_id=enc.encounter_id, readmitted=data.readmitted, **flags))
        _replace_children(session, enc.encounter_id, data.diagnoses, data.medications)
        audit.record(session, ctx, "CREATE", "encounter", enc.encounter_id, None, snapshot(session, enc))
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ApiError(409, "conflict", f"Encounter {data.encounter_id} already exists") from None
    return data.encounter_id


def update(session: Session, ctx: AuditContext, encounter_id: int, data: EncounterUpdate) -> None:
    """Apply the sent fields, re-derive flags, re-validate the merged state, audit UPDATE, commit once."""
    enc = _active_encounter(session, encounter_id)
    outcome = session.get(EncounterOutcome, encounter_id)
    before = snapshot(session, enc)
    sent = data.model_fields_set
    for field in sent & set(_SCALARS):
        setattr(enc, field, getattr(data, field))
    if "age_group" in sent:
        enc.age_order = AGE_ORDER[data.age_group]  # type: ignore[index]
    problems = stay_problems(enc.admission_date, enc.discharge_date, enc.time_in_hospital)
    problems += content_problems(data.diagnoses, data.medications)
    problems += _check_lookups(session, enc.admission_type_id, enc.discharge_disposition_id, enc.admission_source_id)
    if problems:
        session.rollback()
        raise _errors(problems)
    if "medical_specialty" in sent or "payer_code" in sent:
        current = before
        spec = data.medical_specialty if "medical_specialty" in sent else current["medical_specialty"]
        pay = data.payer_code if "payer_code" in sent else current["payer_code"]
        enc.specialty_id, enc.payer_id = _resolve_lookup_ids(session, spec, pay)
    if outcome is not None and ({"readmitted", "discharge_disposition_id"} & sent):
        outcome.readmitted = data.readmitted if "readmitted" in sent else outcome.readmitted
        for k, v in derive_flags(outcome.readmitted, enc.discharge_disposition_id).items():
            setattr(outcome, k, v)
    _replace_children(session, encounter_id, data.diagnoses if "diagnoses" in sent else None,
                      data.medications if "medications" in sent else None)
    audit.record(session, ctx, "UPDATE", "encounter", encounter_id, before, snapshot(session, enc))
    session.commit()


def soft_delete(session: Session, ctx: AuditContext, encounter_id: int) -> None:
    """Soft delete (is_deleted + deleted_at), audit DELETE, commit once."""
    enc = _active_encounter(session, encounter_id)
    before = snapshot(session, enc)
    enc.is_deleted, enc.deleted_at = True, datetime.now()
    audit.record(session, ctx, "DELETE", "encounter", encounter_id, before, snapshot(session, enc))
    session.commit()


# ---- reads (through the view) -------------------------------------------------------------------------------
def _shape(row: dict[str, Any], role: str) -> dict[str, Any]:
    """Apply role minimisation and mark the dates as simulated (set explicitly so response_model_exclude_unset keeps it)."""
    if is_minimised("list_encounters", role):
        row = {k: v for k, v in row.items() if k not in MINIMISED_DROP}
    return {**row, "dates_simulated": True}


def get_detail(session: Session, encounter_id: int, role: str) -> dict[str, Any]:
    """One active encounter with diagnoses and medications; 404 if absent or soft-deleted. Role-minimised."""
    row = session.execute(select(V).where(V.c.encounter_id == encounter_id)).first()
    if row is None:
        raise _not_found(encounter_id)
    out = dict(row._mapping)
    out["diagnoses"] = [{"position": p, "icd9_code": c} for p, c in session.execute(select(
        EncounterDiagnosis.position, EncounterDiagnosis.icd9_code).where(
        EncounterDiagnosis.encounter_id == encounter_id).order_by(EncounterDiagnosis.position))]
    out["medications"] = [{"drug_name": n, "dosage_status": s} for n, s in session.execute(select(
        Medication.drug_name, EncounterMedication.dosage_status).join(
        EncounterMedication, EncounterMedication.medication_id == Medication.medication_id).where(
        EncounterMedication.encounter_id == encounter_id).order_by(Medication.drug_name))]
    return _shape(out, role)


def search_condition(q: str | None, role: str) -> Any:
    """q semantics: digits only -> exact encounter_id (or patient_nbr, not for analysts); otherwise an ICD-9 prefix."""
    if q is None or not q.strip():
        return None
    text = q.strip()
    if text.isdigit():
        if len(text) > 19:
            raise validation_error("q", "numeric q is too long")
        number = int(text)
        if is_minimised("list_encounters", role):
            return V.c.encounter_id == number
        return or_(V.c.encounter_id == number, V.c.patient_nbr == number)
    if not _ICD_PREFIX.match(text):
        raise validation_error("q", "q must be a number (id) or an ICD-9 prefix such as 250 or V57 or 250.8")
    return exists().where(EncounterDiagnosis.encounter_id == V.c.encounter_id,
                          EncounterDiagnosis.icd9_code.startswith(text.upper(), autoescape=True))


def list_encounters(session: Session, role: str, params: PageParams, sort_by: str, sort_dir: str,
                    filters: dict[str, Any]) -> dict[str, Any]:
    """Filtered, sorted, paginated active encounters. ``filters`` keys are the documented query parameters."""
    f = filters
    check_date_range(f.get("date_from"), f.get("date_to"))
    if f.get("min_los") is not None and f.get("max_los") is not None and f["min_los"] > f["max_los"]:
        raise validation_error("min_los", "min_los must not be greater than max_los")
    if f.get("patient_nbr") is not None and is_minimised("list_encounters", role):
        raise ApiError(403, "forbidden", "Filtering by patient_nbr is not permitted for this role")
    conditions = [
        *inclusive_day_range(V.c.admission_date, f.get("date_from"), f.get("date_to")),
        V.c.age_group == f["age_group"] if f.get("age_group") else None,
        V.c.admission_type_id == f["admission_type_id"] if f.get("admission_type_id") is not None else None,
        V.c.admission_source_id == f["admission_source_id"] if f.get("admission_source_id") is not None else None,
        V.c.discharge_disposition_id == f["discharge_disposition_id"]
        if f.get("discharge_disposition_id") is not None else None,
        V.c.medical_specialty == f["specialty"] if f.get("specialty") else None,
        V.c.readmitted == f["readmitted"] if f.get("readmitted") else None,
        V.c.time_in_hospital >= f["min_los"] if f.get("min_los") is not None else None,
        V.c.time_in_hospital <= f["max_los"] if f.get("max_los") is not None else None,
        V.c.patient_nbr == f["patient_nbr"] if f.get("patient_nbr") is not None else None,
        search_condition(f.get("q"), role),
    ]
    stmt = apply_sort(apply_filters(select(V), conditions), ENCOUNTER_SORT, sort_by, sort_dir)
    return paginate(session, stmt, params, lambda r: _shape(dict(r._mapping), role))


def patient_encounters(session: Session, patient_nbr: int, role: str, params: PageParams, sort_by: str,
                       sort_dir: str) -> dict[str, Any]:
    """Active encounters of one patient (the patient must be active, else 404)."""
    from app.services.patients import get_active
    get_active(session, patient_nbr)
    return list_encounters(session, role, params, sort_by, sort_dir, {"patient_nbr": patient_nbr})


