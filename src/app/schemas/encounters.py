"""Encounter schemas. Derived outcome flags are NEVER accepted from the client (extra input is ignored)."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from etl.quality import DISCHARGE_GRACE_DAYS, ICD9_PATTERN, NUMERIC_RANGES, WINDOW_END, WINDOW_START
from etl.transform import MEDICATION_COLUMNS

AgeGroup = Literal["[0-10)", "[10-20)", "[20-30)", "[30-40)", "[40-50)", "[50-60)", "[60-70)", "[70-80)", "[80-90)",
                   "[90-100)"]
Readmitted = Literal["NO", ">30", "<30"]
Glucose = Literal["None", "Norm", ">200", ">300"]
A1c = Literal["None", "Norm", ">7", ">8"]
Dosage = Literal["Steady", "Up", "Down"]
_ICD = re.compile(ICD9_PATTERN)


def rng(name: str) -> Any:
    """Field with the same inclusive bounds the ETL data-quality rule DQ05 uses (single source of truth)."""
    low, high = NUMERIC_RANGES[name]
    return Field(ge=low, le=high)


def stay_problems(admission: date, discharge: date, los: int) -> list[tuple[str, str]]:
    """(field, message) for each problem with a date pair and length of stay (same rules as DQ08-DQ10)."""
    problems: list[tuple[str, str]] = []
    if not WINDOW_START.date() <= admission <= WINDOW_END.date():
        problems.append(("admission_date", "admission_date must be within 1999-01-01..2008-12-31 (simulated study window)"))
    if discharge > WINDOW_END.date() + timedelta(days=DISCHARGE_GRACE_DAYS):
        problems.append(("discharge_date", "discharge_date is after the study window"))
    if discharge < admission:
        problems.append(("discharge_date", "discharge_date must not be before admission_date"))
    elif (discharge - admission).days != los:
        problems.append(("discharge_date", f"discharge_date minus admission_date must equal time_in_hospital ({los} days)"))
    return problems


class DiagnosisIn(BaseModel):
    """One ICD-9 code (always a string) at position 1-3; position 1 is the primary diagnosis."""

    position: int = Field(ge=1, le=3)
    icd9_code: str = Field(max_length=10)

    @field_validator("icd9_code")
    @classmethod
    def _icd(cls, value: str) -> str:
        if not _ICD.match(value):
            raise ValueError("invalid ICD-9 code format")
        return value


class MedicationIn(BaseModel):
    """A prescribed drug. 'No' is not accepted: unprescribed drugs are simply absent."""

    drug_name: str
    dosage_status: Dosage

    @field_validator("drug_name")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in MEDICATION_COLUMNS:
            raise ValueError(f"unknown drug; allowed: {', '.join(MEDICATION_COLUMNS)}")
        return value


def content_problems(diagnoses: list[Any] | None, medications: list[Any] | None) -> list[tuple[str, str]]:
    """(field, message) for duplicate diagnosis positions or duplicate drugs (reported against the field)."""
    problems: list[tuple[str, str]] = []
    positions = [d.position for d in diagnoses or []]
    if len(positions) != len(set(positions)):
        problems.append(("diagnoses", "duplicate diagnosis position"))
    drugs = [m.drug_name for m in medications or []]
    if len(drugs) != len(set(drugs)):
        problems.append(("medications", "the same drug appears more than once"))
    return problems


class EncounterCreate(BaseModel):
    """Create an encounter with nested diagnoses and medications. readmitted_30d and eligibility are computed server-side."""

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "encounter_id": 900000001, "patient_nbr": 900000001, "admission_date": "2005-03-01",
        "discharge_date": "2005-03-04", "age_group": "[70-80)", "admission_type_id": 1,
        "discharge_disposition_id": 1, "admission_source_id": 7, "medical_specialty": "Cardiology",
        "payer_code": "MC", "time_in_hospital": 3, "num_lab_procedures": 40, "num_procedures": 1,
        "num_medications": 12, "number_outpatient": 0, "number_emergency": 0, "number_inpatient": 0,
        "number_diagnoses": 3, "max_glu_serum": "None", "a1c_result": "None", "med_changed": False,
        "diabetes_med": True, "readmitted": "NO",
        "diagnoses": [{"position": 1, "icd9_code": "250.83"}, {"position": 2, "icd9_code": "401.9"}],
        "medications": [{"drug_name": "insulin", "dosage_status": "Steady"}]}]})

    encounter_id: int = Field(gt=0, le=9_223_372_036_854_775_807)
    patient_nbr: int = Field(gt=0, le=9_223_372_036_854_775_807)
    admission_date: date
    discharge_date: date
    age_group: AgeGroup
    admission_type_id: int
    discharge_disposition_id: int
    admission_source_id: int
    medical_specialty: str | None = Field(None, max_length=80)
    payer_code: str | None = Field(None, max_length=10)
    time_in_hospital: int = rng("time_in_hospital")
    num_lab_procedures: int = rng("num_lab_procedures")
    num_procedures: int = rng("num_procedures")
    num_medications: int = rng("num_medications")
    number_outpatient: int = rng("number_outpatient")
    number_emergency: int = rng("number_emergency")
    number_inpatient: int = rng("number_inpatient")
    number_diagnoses: int = rng("number_diagnoses")
    max_glu_serum: Glucose
    a1c_result: A1c
    med_changed: bool
    diabetes_med: bool
    readmitted: Readmitted
    diagnoses: list[DiagnosisIn] = Field(default_factory=list, max_length=3)
    medications: list[MedicationIn] = Field(default_factory=list)

NON_NULLABLE = ("admission_date", "discharge_date", "age_group", "admission_type_id", "discharge_disposition_id",
                "admission_source_id", "time_in_hospital", "num_lab_procedures", "num_procedures", "num_medications",
                "number_outpatient", "number_emergency", "number_inpatient", "number_diagnoses", "max_glu_serum",
                "a1c_result", "med_changed", "diabetes_med", "readmitted", "diagnoses", "medications")


class EncounterUpdate(BaseModel):
    """Partial update. encounter_id and patient_nbr cannot change. Sending diagnoses or medications replaces the whole set."""

    model_config = ConfigDict(json_schema_extra={"examples": [{"readmitted": "<30", "number_inpatient": 1}]})

    admission_date: date | None = None
    discharge_date: date | None = None
    age_group: AgeGroup | None = None
    admission_type_id: int | None = None
    discharge_disposition_id: int | None = None
    admission_source_id: int | None = None
    medical_specialty: str | None = Field(None, max_length=80)
    payer_code: str | None = Field(None, max_length=10)
    time_in_hospital: int | None = Field(None, ge=NUMERIC_RANGES["time_in_hospital"][0], le=NUMERIC_RANGES["time_in_hospital"][1])
    num_lab_procedures: int | None = Field(None, ge=0, le=NUMERIC_RANGES["num_lab_procedures"][1])
    num_procedures: int | None = Field(None, ge=0, le=NUMERIC_RANGES["num_procedures"][1])
    num_medications: int | None = Field(None, ge=0, le=NUMERIC_RANGES["num_medications"][1])
    number_outpatient: int | None = Field(None, ge=0, le=NUMERIC_RANGES["number_outpatient"][1])
    number_emergency: int | None = Field(None, ge=0, le=NUMERIC_RANGES["number_emergency"][1])
    number_inpatient: int | None = Field(None, ge=0, le=NUMERIC_RANGES["number_inpatient"][1])
    number_diagnoses: int | None = Field(None, ge=0, le=NUMERIC_RANGES["number_diagnoses"][1])
    max_glu_serum: Glucose | None = None
    a1c_result: A1c | None = None
    med_changed: bool | None = None
    diabetes_med: bool | None = None
    readmitted: Readmitted | None = None
    diagnoses: list[DiagnosisIn] | None = Field(None, max_length=3)
    medications: list[MedicationIn] | None = None

    @model_validator(mode="after")
    def _valid(self) -> "EncounterUpdate":
        if not self.model_fields_set:
            raise ValueError("send at least one field to change")
        for name in NON_NULLABLE:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class DiagnosisOut(BaseModel):
    position: int
    icd9_code: str


class MedicationOut(BaseModel):
    drug_name: str
    dosage_status: str


class EncounterOut(BaseModel):
    """An encounter. For the analyst role patient_nbr and source_batch_id are never set, so they are omitted."""

    encounter_id: int
    patient_nbr: int | None = Field(None, description="omitted for the analyst role (data minimisation)")
    admission_date: date = Field(description="SIMULATED")
    discharge_date: date = Field(description="SIMULATED")
    age_group: str
    age_order: int
    admission_type_id: int
    admission_type: str
    admission_source_id: int
    admission_source: str
    discharge_disposition_id: int
    discharge_disposition: str
    medical_specialty: str | None
    payer_code: str | None
    time_in_hospital: int
    num_lab_procedures: int
    num_procedures: int
    num_medications: int
    number_outpatient: int
    number_emergency: int
    number_inpatient: int
    number_diagnoses: int
    max_glu_serum: str
    a1c_result: str
    med_changed: bool
    diabetes_med: bool
    readmitted: str
    readmitted_30d: bool
    any_readmission: bool
    is_readmission_eligible: bool
    source_batch_id: str | None = Field(None, description="omitted for the analyst role")
    diagnoses: list[DiagnosisOut] | None = None
    medications: list[MedicationOut] | None = None
    dates_simulated: bool = True

