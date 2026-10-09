"""Read-only analytics endpoints (all roles). Aggregates are computed in the database; no race or gender anywhere."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query

from app.deps import CurrentUser, DbSession, require_capability
from app.schemas.analytics import (
    GroupResponse, LengthOfStayResponse, MedicationsResponse, SummaryResponse,
)
from app.schemas.encounters import AgeGroup
from app.services import analytics as service

router = APIRouter(prefix="/analytics", tags=["analytics"])
Reader = Annotated[CurrentUser, Depends(require_capability("dashboards"))]


def shared_filters(date_from: date | None = Query(None, description="admission_date >= (inclusive; SIMULATED)"),
                   date_to: date | None = Query(None, description="admission_date <= (inclusive)"),
                   age_group: AgeGroup | None = None,
                   admission_type_id: int | None = Query(None, ge=1)) -> dict[str, Any]:
    """The four filters every analytics endpoint accepts."""
    return {"date_from": date_from, "date_to": date_to, "age_group": age_group, "admission_type_id": admission_type_id}


Filters = Annotated[dict[str, Any], Depends(shared_filters)]


@router.get("/summary", response_model=SummaryResponse, summary="Headline KPIs")
def summary(db: DbSession, user: Reader, f: Filters) -> dict:
    """Total encounters, unique patients, average LOS, 30-day and any-readmission rates (eligible denominator)."""
    return {"data": service.summary(db, f), "meta": service.meta(f)}


@router.get("/admissions-trend", response_model=GroupResponse, summary="Encounters and readmission rate per month or year")
def admissions_trend(db: DbSession, user: Reader, f: Filters,
                     granularity: Literal["month", "year"] = "month") -> dict:
    """Periods with no encounters are omitted. Dates are simulated."""
    return {"data": service.admissions_trend(db, granularity, f), "meta": service.meta({**f, "granularity": granularity})}


@router.get("/length-of-stay", response_model=LengthOfStayResponse, summary="Length of stay by group, with histogram")
def length_of_stay(db: DbSession, user: Reader, f: Filters,
                   group_by: Literal["age_group", "admission_type", "admission_source", "specialty", "overall"] = "age_group") -> dict:
    return {"data": service.length_of_stay(db, group_by, f), "meta": service.meta({**f, "group_by": group_by})}


@router.get("/readmissions", response_model=GroupResponse, summary="30-day readmission rate by group")
def readmissions(db: DbSession, user: Reader, f: Filters,
                 group_by: Literal["age_group", "admission_type", "admission_source", "discharge_disposition",
                                   "specialty", "month"] = "age_group") -> dict:
    """age_group is ordered by age_order, month chronologically, the rest by volume. Rates use eligible encounters."""
    return {"data": service.readmissions(db, group_by, f), "meta": service.meta({**f, "group_by": group_by})}


@router.get("/medications", response_model=MedicationsResponse, summary="Top drugs, insulin status and A1C vs readmission")
def medications(db: DbSession, user: Reader, f: Filters) -> dict:
    return {"data": service.medications(db, f), "meta": service.meta(f)}


@router.get("/utilization", response_model=GroupResponse, summary="Prior inpatient visits vs readmission")
def utilization(db: DbSession, user: Reader, f: Filters) -> dict:
    return {"data": service.utilization(db, f), "meta": service.meta(f)}
