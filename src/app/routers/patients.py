"""Patient endpoints. Roles: administrator all; clinical_ops all except DELETE; analyst 403 on every route."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select

from app.deps import CurrentUser, DbSession, require_capability
from app.errors import ApiError
from app.schemas.common import Page
from app.schemas.encounters import EncounterOut
from app.schemas.patients import PatientCreate, PatientOut, PatientUpdate
from app.services import encounters as enc_service
from app.services import patients as service
from app.services.audit import audit_context
from app.services.query_helpers import PageParams, envelope, page_params

router = APIRouter(prefix="/patients", tags=["patients"])
Reader = Annotated[CurrentUser, Depends(require_capability("view_patients"))]
Writer = Annotated[CurrentUser, Depends(require_capability("write_records"))]
Deleter = Annotated[CurrentUser, Depends(require_capability("delete_records"))]
Paging = Annotated[PageParams, Depends(page_params)]


@router.post("", response_model=PatientOut, status_code=201, summary="Create a patient")
def create_patient(body: PatientCreate, request: Request, db: DbSession, user: Writer) -> PatientOut:
    """409 if the patient_nbr already exists. Audited (CREATE)."""
    patient = service.create(db, audit_context(request, user), body)
    return PatientOut.model_validate(patient, from_attributes=True)


@router.get("", response_model=Page[PatientOut], summary="List and search patients")
def list_patients(db: DbSession, user: Reader, params: Paging,
                  q: int | None = Query(None, gt=0, description="exact patient_nbr"),
                  has_multiple_encounters: bool | None = Query(None, description="true: more than one active encounter"),
                  sort_by: Literal["patient_nbr", "created_at"] = "patient_nbr",
                  sort_dir: Literal["asc", "desc"] = "asc") -> dict:
    """Paginated, sorted list (ties broken by patient_nbr)."""
    page = service.list_patients(db, params, q, has_multiple_encounters, sort_by, sort_dir)
    return envelope(page, {"q": q, "has_multiple_encounters": has_multiple_encounters}, sort_by, sort_dir)


@router.get("/{patient_nbr}", response_model=PatientOut, summary="Get one patient")
def get_patient(patient_nbr: int, db: DbSession, user: Reader) -> PatientOut:
    """404 if missing or soft-deleted."""
    return PatientOut.model_validate(service.get_active(db, patient_nbr), from_attributes=True)


@router.put("/{patient_nbr}", response_model=PatientOut, summary="Update a patient (partial)")
def update_patient(patient_nbr: int, body: PatientUpdate, request: Request, db: DbSession, user: Writer) -> PatientOut:
    """Only the fields sent change. Audited (UPDATE) with before/after."""
    patient = service.update(db, audit_context(request, user), patient_nbr, body)
    return PatientOut.model_validate(patient, from_attributes=True)


@router.delete("/{patient_nbr}", status_code=204, summary="Soft-delete a patient (administrator only)")
def delete_patient(patient_nbr: int, request: Request, db: DbSession, user: Deleter) -> Response:
    """Sets is_deleted; the patient's encounters vanish from every read. Audited (DELETE)."""
    service.soft_delete(db, audit_context(request, user), patient_nbr)
    return Response(status_code=204)


@router.get("/{patient_nbr}/encounters", response_model=Page[EncounterOut], response_model_exclude_unset=True,
            summary="Active encounters of one patient")
def patient_encounters(patient_nbr: int, db: DbSession, user: Reader, params: Paging,
                       sort_by: Literal["encounter_id", "admission_date", "time_in_hospital", "num_medications",
                                        "number_inpatient", "age_order"] = "admission_date",
                       sort_dir: Literal["asc", "desc"] = "desc") -> dict:
    """Same envelope and encounter shape as GET /encounters."""
    page = enc_service.patient_encounters(db, patient_nbr, user.role, params, sort_by, sort_dir)
    return envelope(page, {"patient_nbr": patient_nbr}, sort_by, sort_dir, dates_simulated=True)
