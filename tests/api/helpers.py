"""Test data builders: insert encounters straight through the ORM (independent of the API under test)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    Encounter, EncounterDiagnosis, EncounterMedication, EncounterOutcome, Medication, Patient, RefMedicalSpecialty,
)
from etl.transform import AGE_ORDER, EXPIRED_OR_HOSPICE_IDS


def _specialty_id(session: Session, name: str | None) -> int | None:
    if not name:
        return None
    row = session.query(RefMedicalSpecialty).filter_by(name=name).one_or_none()
    if row is None:
        row = RefMedicalSpecialty(name=name)
        session.add(row)
        session.flush()
    return row.specialty_id


def _drug_id(session: Session, name: str) -> int:
    row = session.query(Medication).filter_by(drug_name=name).one_or_none()
    if row is None:
        row = Medication(drug_name=name)
        session.add(row)
        session.flush()
    return row.medication_id


def add_encounter(session: Session, encounter_id: int, patient_nbr: int, *, admission: date, los: int = 3,
                  age_group: str = "[70-80)", admission_type_id: int = 1, admission_source_id: int = 7,
                  disposition_id: int = 1, specialty: str | None = None, readmitted: str = "NO",
                  number_inpatient: int = 0, a1c: str = "None", drugs: dict[str, str] | None = None,
                  diagnoses: tuple[str, ...] = ("250.00",), deleted: bool = False, race: str = "Caucasian",
                  gender: str = "Female") -> None:
    """Insert one patient (if new), one encounter, its outcome, diagnoses and medications."""
    if session.get(Patient, patient_nbr) is None:
        session.add(Patient(patient_nbr=patient_nbr, race=race, gender=gender))
        session.flush()
    session.add(Encounter(
        encounter_id=encounter_id, patient_nbr=patient_nbr, admission_date=admission,
        discharge_date=admission + timedelta(days=los), age_group=age_group, age_order=AGE_ORDER[age_group],
        admission_type_id=admission_type_id, discharge_disposition_id=disposition_id,
        admission_source_id=admission_source_id, specialty_id=_specialty_id(session, specialty),
        time_in_hospital=los, num_lab_procedures=40, num_procedures=1, num_medications=10, number_outpatient=0,
        number_emergency=0, number_inpatient=number_inpatient, number_diagnoses=len(diagnoses),
        max_glu_serum="None", a1c_result=a1c, med_changed=False, diabetes_med=True, source_batch_id="test",
        is_deleted=deleted, deleted_at=datetime.now() if deleted else None))
    session.flush()
    session.add(EncounterOutcome(
        encounter_id=encounter_id, readmitted=readmitted, readmitted_30d=readmitted == "<30",
        any_readmission=readmitted in ("<30", ">30"),
        is_readmission_eligible=disposition_id not in EXPIRED_OR_HOSPICE_IDS))
    session.add_all(EncounterDiagnosis(encounter_id=encounter_id, position=i, icd9_code=c)
                    for i, c in enumerate(diagnoses, start=1))
    for drug, status in (drugs or {}).items():
        session.add(EncounterMedication(encounter_id=encounter_id, medication_id=_drug_id(session, drug),
                                        dosage_status=status))
    session.flush()


def valid_payload(**overrides: Any) -> dict[str, Any]:
    """A valid POST /encounters body (admission 2005-03-01, 3-day stay); override any field."""
    body: dict[str, Any] = {
        "encounter_id": 900000001, "patient_nbr": 900000001, "admission_date": "2005-03-01",
        "discharge_date": "2005-03-04", "age_group": "[70-80)", "admission_type_id": 1,
        "discharge_disposition_id": 1, "admission_source_id": 7, "medical_specialty": "Cardiology", "payer_code": "MC",
        "time_in_hospital": 3, "num_lab_procedures": 40, "num_procedures": 1, "num_medications": 12,
        "number_outpatient": 0, "number_emergency": 0, "number_inpatient": 0, "number_diagnoses": 3,
        "max_glu_serum": "None", "a1c_result": "None", "med_changed": False, "diabetes_med": True, "readmitted": "NO",
        "diagnoses": [{"position": 1, "icd9_code": "250.83"}, {"position": 2, "icd9_code": "401.9"}],
        "medications": [{"drug_name": "insulin", "dosage_status": "Steady"}]}
    body.update(overrides)
    return body


# ---- the 40-row fixture shared by the analytics and report tests (hand calculations: see test_analytics.py) -----------
R30 = {2, 3, 5, 12, 13, 14, 28, 40}
GT30 = {1, 4, 20, 21}
DISPOSITION = {5: 11, 12: 13, 30: 14}
INPATIENT = {2: 1, 3: 1, 13: 2, 14: 3, 28: 4}
INSULIN = {1: "Steady", 2: "Steady", 3: "Steady", 13: "Up", 28: "Down"}
START = date(2005, 1, 1)


def age_of(i: int) -> str:
    return "[50-60)" if i <= 10 else "[70-80)" if i <= 25 else "[80-90)"


def admission_of(i: int) -> date:
    return START + timedelta(days=15 * (i - 1))


def load_forty(session: Session) -> None:
    """Encounters 1..40 (id 40 soft-deleted). See the HAND CALCULATIONS block in test_analytics.py."""
    for i in range(1, 41):
        drugs = {}
        if i in INSULIN:
            drugs["insulin"] = INSULIN[i]
        if i in (1, 2):
            drugs["metformin"] = "Steady"
        add_encounter(
            session, i, 100 if i in (21, 22, 23) else i, admission=admission_of(i), los=(i % 5) + 1, age_group=age_of(i),
            admission_type_id=1 if i <= 30 else 2, disposition_id=DISPOSITION.get(i, 1),
            specialty="Cardiology" if i <= 10 else None,
            readmitted="<30" if i in R30 else ">30" if i in GT30 else "NO", number_inpatient=INPATIENT.get(i, 0),
            a1c="Norm" if i in (1, 2) else ">8" if i == 28 else "None", drugs=drugs, deleted=i == 40)