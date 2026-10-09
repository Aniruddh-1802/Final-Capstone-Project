"""Import every model so Base.metadata knows all tables."""
from app.models.base import Base
from app.models.clinical import EncounterDiagnosis, EncounterMedication, EncounterOutcome, Medication
from app.models.encounters import Encounter
from app.models.ops import AuditLog, DqIssue, PipelineRun, ReportRun
from app.models.patients import Patient
from app.models.reference import (
    RefAdmissionSource,
    RefAdmissionType,
    RefDischargeDisposition,
    RefMedicalSpecialty,
    RefPayer,
)
from app.models.users import AppUser

__all__ = [
    "Base", "Patient", "Encounter", "EncounterOutcome", "EncounterDiagnosis", "Medication",
    "EncounterMedication", "RefAdmissionType", "RefAdmissionSource", "RefDischargeDisposition",
    "RefMedicalSpecialty", "RefPayer", "AppUser", "AuditLog", "PipelineRun", "DqIssue", "ReportRun",
]
