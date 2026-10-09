"""Small read-only lookup lists for forms and filters. Any authenticated role may read them (they hold no personal data)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.deps import CurrentUser, DbSession, get_current_user
from app.models import RefAdmissionSource, RefAdmissionType, RefDischargeDisposition, RefMedicalSpecialty
from etl.transform import AGE_BRACKETS

router = APIRouter(prefix="/reference", tags=["reference"], dependencies=[Depends(get_current_user)])
Caller = Annotated[CurrentUser, Depends(get_current_user)]


class RefItem(BaseModel):
    id: int
    label: str


class DispositionItem(RefItem):
    is_expired_or_hospice: bool


@router.get("/admission-types", response_model=list[RefItem])
def admission_types(db: DbSession) -> list[dict]:
    return [{"id": r.id, "label": r.description} for r in db.scalars(select(RefAdmissionType).order_by(RefAdmissionType.id))]


@router.get("/admission-sources", response_model=list[RefItem])
def admission_sources(db: DbSession) -> list[dict]:
    return [{"id": r.id, "label": r.description} for r in db.scalars(select(RefAdmissionSource).order_by(RefAdmissionSource.id))]


@router.get("/discharge-dispositions", response_model=list[DispositionItem])
def discharge_dispositions(db: DbSession) -> list[dict]:
    return [{"id": r.id, "label": r.description, "is_expired_or_hospice": bool(r.is_expired_or_hospice)}
            for r in db.scalars(select(RefDischargeDisposition).order_by(RefDischargeDisposition.id))]


@router.get("/specialties", response_model=list[RefItem])
def specialties(db: DbSession) -> list[dict]:
    return [{"id": r.specialty_id, "label": r.name} for r in db.scalars(select(RefMedicalSpecialty).order_by(RefMedicalSpecialty.name))]


@router.get("/age-groups", response_model=list[RefItem], summary="Age groups in clinical order (id = age_order)")
def age_groups() -> list[dict]:
    return [{"id": i, "label": label} for i, label in enumerate(AGE_BRACKETS, start=1)]
