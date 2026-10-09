"""Patient schemas. Race and gender are only ever returned by the /patients endpoints (never to analysts)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Gender = Literal["Male", "Female", "Unknown"]


def _clean(value: str | None) -> str | None:
    return value.strip() or None if isinstance(value, str) else value


class PatientCreate(BaseModel):
    """Create a patient. patient_nbr is the source key (never generated)."""

    model_config = ConfigDict(json_schema_extra={"examples": [
        {"patient_nbr": 900000001, "race": "Caucasian", "gender": "Female"}]})

    patient_nbr: int = Field(gt=0, le=9_223_372_036_854_775_807)
    race: str | None = Field(None, max_length=30)
    gender: Gender | None = None

    _strip = field_validator("race", mode="before")(_clean)


class PatientUpdate(BaseModel):
    """Partial update: only the fields sent are changed; an explicit null clears the value."""

    model_config = ConfigDict(json_schema_extra={"examples": [{"gender": "Unknown"}]})

    race: str | None = Field(None, max_length=30)
    gender: Gender | None = None

    _strip = field_validator("race", mode="before")(_clean)

    @model_validator(mode="after")
    def _something_to_change(self) -> "PatientUpdate":
        if not self.model_fields_set:
            raise ValueError("send at least one of: race, gender")
        return self


class PatientOut(BaseModel):
    """A patient record (administrator and clinical_ops only)."""

    patient_nbr: int
    race: str | None
    gender: str | None
    created_at: datetime
    updated_at: datetime
    encounter_count: int | None = Field(None, description="active (non-deleted) encounters; only set in lists")
