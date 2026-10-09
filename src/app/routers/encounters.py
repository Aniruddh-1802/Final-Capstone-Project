"""Encounter endpoints. Analyst: read-only and minimised (no patient_nbr). Writes need write_records; delete is admin only."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from app.deps import CurrentUser, DbSession, require_capability
from app.schemas.common import Page
from app.schemas.encounters import AgeGroup, EncounterCreate, EncounterOut, EncounterUpdate, Readmitted
from app.services import encounters as service
from app.services.audit import audit_context
from app.services.query_helpers import PageParams, envelope, page_params

router = APIRouter(prefix="/encounters", tags=["encounters"])
Reader = Annotated[CurrentUser, Depends(require_capability("list_encounters"))]
Writer = Annotated[CurrentUser, Depends(require_capability("write_records"))]
Deleter = Annotated[CurrentUser, Depends(require_capability("delete_records"))]
Paging = Annotated[PageParams, Depends(page_params)]
SortBy = Literal["encounter_id", "admission_date", "time_in_hospital", "num_medications", "number_inpatient", "age_order"]


@router.post("", response_model=EncounterOut, response_model_exclude_unset=True, status_code=201,
             summary="Create an encounter")
def create_encounter(body: EncounterCreate, request: Request, db: DbSession, user: Writer) -> dict:
    """Validated create. readmitted_30d / is_readmission_eligible are derived on the server. 409 on duplicate id."""
    encounter_id = service.create(db, audit_context(request, user), body)
    return service.get_detail(db, encounter_id, user.role)


@router.get("", response_model=Page[EncounterOut], response_model_exclude_unset=True,
            summary="List and search encounters")
def list_encounters(
    db: DbSession, user: Reader, params: Paging,
    sort_by: SortBy = "admission_date", sort_dir: Literal["asc", "desc"] = "desc",
    date_from: date | None = Query(None, description="admission_date >= (inclusive; SIMULATED dates)"),
    date_to: date | None = Query(None, description="admission_date <= (inclusive)"),
    age_group: AgeGroup | None = None,
    admission_type_id: int | None = Query(None, ge=1), admission_source_id: int | None = Query(None, ge=1),
    discharge_disposition_id: int | None = Query(None, ge=1),
    specialty: str | None = Query(None, max_length=80, description="exact medical specialty name"),
    readmitted: Readmitted | None = None,
    min_los: int | None = Query(None, ge=1, le=14), max_los: int | None = Query(None, ge=1, le=14),
    patient_nbr: int | None = Query(None, gt=0, description="not allowed for the analyst role"),
    q: str | None = Query(None, max_length=19,
                          description="digits only: exact encounter_id (or patient_nbr); otherwise an ICD-9 prefix match"),
) -> dict:
    """Filters combine with AND. Paging is stable: the sort column is always followed by encounter_id."""
    filters = {"date_from": date_from, "date_to": date_to, "age_group": age_group,
               "admission_type_id": admission_type_id, "admission_source_id": admission_source_id,
               "discharge_disposition_id": discharge_disposition_id, "specialty": specialty, "readmitted": readmitted,
               "min_los": min_los, "max_los": max_los, "patient_nbr": patient_nbr, "q": q}
    page = service.list_encounters(db, user.role, params, sort_by, sort_dir, filters)
    return envelope(page, filters, sort_by, sort_dir, dates_simulated=True)


@router.get("/{encounter_id}", response_model=EncounterOut, response_model_exclude_unset=True,
            summary="Get one encounter with diagnoses and medications")
def get_encounter(encounter_id: int, db: DbSession, user: Reader) -> dict:
    """404 if missing or soft-deleted. The analyst response has no patient_nbr."""
    return service.get_detail(db, encounter_id, user.role)


@router.put("/{encounter_id}", response_model=EncounterOut, response_model_exclude_unset=True,
            summary="Update an encounter (partial)")
def update_encounter(encounter_id: int, body: EncounterUpdate, request: Request, db: DbSession, user: Writer) -> dict:
    """Only the fields sent change; flags are re-derived; the merged state is re-validated. Audited (UPDATE)."""
    service.update(db, audit_context(request, user), encounter_id, body)
    return service.get_detail(db, encounter_id, user.role)


@router.delete("/{encounter_id}", status_code=204, summary="Soft-delete an encounter (administrator only)")
def delete_encounter(encounter_id: int, request: Request, db: DbSession, user: Deleter) -> Response:
    """Sets is_deleted; the encounter disappears from reads and from v_active_encounters. Audited (DELETE)."""
    service.soft_delete(db, audit_context(request, user), encounter_id)
    return Response(status_code=204)
