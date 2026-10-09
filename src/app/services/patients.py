"""Patient business logic. Routers stay thin; every write audits in the same transaction and commits once."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Encounter, Patient
from app.schemas.patients import PatientCreate, PatientUpdate
from app.services import audit
from app.services.audit import AuditContext
from app.services.query_helpers import PageParams, SortSpec, apply_filters, apply_sort, paginate

log = logging.getLogger(__name__)
PATIENT_SORT = SortSpec(columns={"patient_nbr": Patient.patient_nbr, "created_at": Patient.created_at},
                        default="patient_nbr", tiebreaker=Patient.patient_nbr)


def snapshot(p: Patient) -> dict[str, Any]:
    """Audit view of a patient (no timestamps, so before/after differ only where data changed).

    Race and gender are sensitive: the audit trail records THAT they are set (and, on update, which one changed) but never
    their values, so reading the audit log never discloses demographics.
    """
    return {"patient_nbr": p.patient_nbr, "race_recorded": p.race is not None, "gender_recorded": p.gender is not None,
            "is_deleted": bool(p.is_deleted)}


def not_found(patient_nbr: int) -> ApiError:
    return ApiError(404, "not_found", f"Patient {patient_nbr} not found")


def get_active(session: Session, patient_nbr: int) -> Patient:
    """The patient, or 404 if it does not exist or is soft-deleted."""
    patient = session.get(Patient, patient_nbr)
    if patient is None or patient.is_deleted:
        raise not_found(patient_nbr)
    return patient


def create(session: Session, ctx: AuditContext, data: PatientCreate) -> Patient:
    """Insert a patient (409 if patient_nbr exists, even if soft-deleted) and audit CREATE."""
    if session.get(Patient, data.patient_nbr) is not None:
        raise ApiError(409, "conflict", f"Patient {data.patient_nbr} already exists")
    patient = Patient(patient_nbr=data.patient_nbr, race=data.race, gender=data.gender)
    session.add(patient)
    try:
        session.flush()
        audit.record(session, ctx, "CREATE", "patient", patient.patient_nbr, None, snapshot(patient))
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ApiError(409, "conflict", f"Patient {data.patient_nbr} already exists") from None
    session.refresh(patient)
    return patient


def update(session: Session, ctx: AuditContext, patient_nbr: int, data: PatientUpdate) -> Patient:
    """Apply the fields that were sent; audit UPDATE with before/after."""
    patient = get_active(session, patient_nbr)
    before = snapshot(patient)
    changed = sorted(f for f in data.model_fields_set if getattr(patient, f) != getattr(data, f))
    for field in data.model_fields_set:
        setattr(patient, field, getattr(data, field))
    session.flush()
    audit.record(session, ctx, "UPDATE", "patient", patient_nbr, before, {**snapshot(patient), "changed_fields": changed})
    session.commit()
    session.refresh(patient)
    return patient


def soft_delete(session: Session, ctx: AuditContext, patient_nbr: int) -> None:
    """Soft delete: is_deleted + deleted_at. Their encounters disappear from every read through v_active_encounters."""
    patient = get_active(session, patient_nbr)
    before = snapshot(patient)
    patient.is_deleted, patient.deleted_at = True, datetime.now()
    session.flush()
    audit.record(session, ctx, "DELETE", "patient", patient_nbr, before, snapshot(patient))
    session.commit()


def list_patients(session: Session, params: PageParams, q: int | None, has_multiple: bool | None,
                  sort_by: str, sort_dir: str) -> dict[str, Any]:
    """Active patients with their active-encounter count; optional exact patient_nbr match and multi-encounter filter."""
    counts = (select(Encounter.patient_nbr.label("pn"), func.count().label("n")).where(Encounter.is_deleted.is_(False))
              .group_by(Encounter.patient_nbr).subquery())
    n = func.coalesce(counts.c.n, 0)
    stmt = (select(Patient.patient_nbr, Patient.race, Patient.gender, Patient.created_at, Patient.updated_at,
                   n.label("encounter_count"))
            .outerjoin(counts, counts.c.pn == Patient.patient_nbr))
    stmt = apply_filters(stmt, [Patient.is_deleted.is_(False),
                                Patient.patient_nbr == q if q is not None else None,
                                (n > 1) if has_multiple is True else ((n <= 1) if has_multiple is False else None)])
    stmt = apply_sort(stmt, PATIENT_SORT, sort_by, sort_dir)
    return paginate(session, stmt, params, lambda r: dict(r._mapping))
